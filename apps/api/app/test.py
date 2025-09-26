import os
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence, List

import numpy as np
from dotenv import find_dotenv, load_dotenv
from fastapi import Depends, Header, HTTPException, status
from numpy.typing import NDArray
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from reelix_core.config import EMBEDDING_MODEL
from reelix_retrieval.embedding_loader import load_embeddings_qdrant, load_metadata_qdrant
from reelix_retrieval.vectorstore import connect_qdrant
from reelix_user.taste_profile import build_taste_vector
from reelix_user.types import BuildParams, Interaction, MediaId, UserSignals, UserTasteContext
from reelix_retrieval.query_encoder import Encoder
from reelix_retrieval.base_retriever import BaseRetriever
from reelix_recommendation.first_rec import FirstRecommendPipeline
from reelix_ranking.types import Candidate


from reelix_core.config import (
    NLTK_PATH,
    QDRANT_MOVIE_COLLECTION_NAME,
    QDRANT_TV_COLLECTION_NAME,
)

from reelix_models.custom_models import (
    load_bm25_files,
    load_cross_encoder,
    load_sentence_model,
    setup_intent_classifier,
)

# ===== Supabase Client =====

class SupabaseSettings(BaseSettings):
    supabase_url: str = Field(default_factory=lambda: os.getenv("SUPABASE_URL", ""))
    supabase_anon_key: str = Field(
        default_factory=lambda: os.getenv("SUPABASE_ANON_KEY", "")
    )
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = SupabaseSettings()

def require_bearer_token(authorization: Optional[str] = Header(None)) -> str:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format",
        )
    return token.strip()


def get_supabase_client(user_token: str = Depends(require_bearer_token)):
    """Return a Supabase client authorized as the end user (DB calls go through PostgREST with user JWT)."""
    try:
        from supabase import Client, create_client  # type: ignore

        client: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

        # Critical: attach the user's JWT for DB calls so RLS (auth.uid()) is enforced.
        client.postgrest.auth(user_token)

        return client
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Supabase init failed: {exc}",
        )


def get_current_user_id(
    client=Depends(get_supabase_client), user_token: str = Depends(require_bearer_token)
) -> str:
    """Fetch the current user id (UUID) from GoTrue using the user's token."""
    try:
        # gotrue-python expects the token to be passed explicitly
        resp = client.auth.get_user(user_token)
        user = getattr(resp, "user", None) or getattr(resp, "data", None)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )
        user_id = getattr(user, "id", None) or user.get("id")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user in token"
            )
        return user_id
    except HTTPException:
        raise
    except Exception as exc:
        # If GoTrue call fails, surface as auth error (most common case)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Failed to resolve user: {exc}",
        )


# ===== Fetch User Signals =====

def _ensure_ts(value) -> datetime | None:
    """Normalize timestamps coming from Postgres/Supabase into tz-aware datetimes."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        # Supabase returns ISO strings that may end with `Z`; make them explicit UTC.
        normalized = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def get_user_signals(
    pg,
    user_id: str,
    *,
    media_type: str | None = None,
    interaction_limit: int = 500,
    timestamp_key: str = "occurred_at",
) -> UserSignals:
    try:
        pref_res = (
            pg.postgrest.table("user_preferences")
            .select("genres_include, keywords_include")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        pref_rows = getattr(pref_res, "data", None) or []
        prefs = pref_rows[0] if pref_rows else {}
    except Exception:
        prefs = {}

    try:
        q = (
            pg.postgrest.table("user_interactions")
            .select(f"media_type, media_id, event_type, {timestamp_key}, created_at")
            .eq("user_id", user_id)
        )
        if media_type:
            q = q.eq("media_type", media_type)
        inter_res = (
            q.order(timestamp_key, desc=True)
             .limit(interaction_limit)
             .execute()
        )
        rows = list(getattr(inter_res, "data", None) or [])
    except Exception:
        rows = []

    interactions = [
        Interaction(
            media_type=str(row["media_type"]),
            media_id=int(row["media_id"]),
            kind=row["event_type"],
            ts=ts,
        )
        for row in rows
        if (ts := _ensure_ts(row.get(timestamp_key) or row.get("created_at"))) is not None
    ]

    return UserSignals(
        genres_include=list(prefs.get("genres_include") or []),
        keywords_include=list(prefs.get("keywords_include") or []),
        interactions=interactions,
    )


# ===== Write Taste Vector to DB =====

TABLE = "user_taste_profile"

def upsert_taste_profile(
    sb: Any,
    user_id: str,
    media_type: str,
    vec: np.ndarray,
    debug: dict[str, Any],
    model_name: str = EMBEDDING_MODEL,
    dim=768,
):
    payload = {
        "user_id": user_id,
        "media_type": media_type,
        "model_name": model_name,
        "dim": dim,
        "dense": vec.tolist(),  # pgvector via PostgREST accepts float array
        "positive_n": int(debug["pos_count"]),
        "negative_n": int(debug["neg_count"]),
        "params": debug["params"],
        "last_built_at": "now()",
    }
    sb.postgrest.table(TABLE).upsert(payload).execute()


# ===== Fetch User Taste and Prefs for Recommendation =====

def fetch_user_taste_context(
    sb,
    user_id: str,
    media_type: str = "movie",
) -> UserTasteContext:
    # 1) Taste profile
    try:
        taste_res = (
            sb.postgrest.table("user_taste_profile")
            .select("dense, positive_n, negative_n, last_built_at")
            .eq("user_id", user_id)
            .eq("media_type", media_type)
            .order("last_built_at", desc=True)
            .limit(1)
            .execute()
        )
        taste_data = getattr(taste_res, "data", None) or []
        taste_row = taste_data if isinstance(taste_data, dict) else (taste_data[0] if taste_data else None)
    except Exception:
        taste_row = None

    # 2) Signals
    signals = get_user_signals(sb, user_id, media_type=media_type)

    # 3) Subs + settings
    try:
        subs_res = (
            sb.postgrest.table("user_subscriptions")
            .select("provider_id")
            .eq("user_id", user_id)
            .eq("active", True)
            .execute()
        )
        subs_rows = getattr(subs_res, "data", None) or []
    except Exception:
        subs_rows = []

    try:
        settings_res = (
            sb.postgrest.table("user_settings")
            .select("provider_filter_mode")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        settings_rows = getattr(settings_res, "data", None) or []
        settings_row = settings_rows[0] if settings_rows else {}
    except Exception:
        settings_row = {}

    # 4) Parse vector + counts
    dense = (taste_row or {}).get("dense") if taste_row else None
    taste_vector: list[float] | None = None
    if isinstance(dense, list):
        taste_vector = [float(v) for v in dense]
    elif isinstance(dense, str):
        raw = dense.strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            trimmed = raw.strip("{}")
            items = [i for i in trimmed.split(",") if i]
            try:
                parsed = [float(i) for i in items]
            except ValueError:
                parsed = None
        if isinstance(parsed, list):
            taste_vector = [float(v) for v in parsed]

    def _toi(x): return int(x) if x is not None else None
    positive_n = _toi((taste_row or {}).get("positive_n") if taste_row else None)
    negative_n = _toi((taste_row or {}).get("negative_n") if taste_row else None)

    return UserTasteContext(
        signals=signals,
        taste_vector=taste_vector,
        positive_n=positive_n,
        negative_n=negative_n,
        last_built_at=_ensure_ts((taste_row or {}).get("last_built_at")) if taste_row else None,
        active_subscriptions=[int(r["provider_id"]) for r in subs_rows if r.get("provider_id") is not None],
        provider_filter_mode=settings_row.get("provider_filter_mode") or "SELECTED",
    )



# ===== Dependencies & Bootstrapping ===== 

load_dotenv(find_dotenv(), override=False)

QDRANT_API_KEY = str(os.getenv("QDRANT_API_KEY"))
QDRANT_ENDPOINT = str(os.getenv("QDRANT_ENDPOINT"))
SUPABASE_URL = str(os.getenv("SUPABASE_URL"))
SUPABASE_ANON_KEY = str(os.getenv("SUPABASE_ANON_KEY"))

TEST_ACCESS_TOKEN = "eyJhbGciOiJIUzI1NiIsImtpZCI6IndVTWNiVm9BM253TU9yMTEiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJodHRwczovL3l5Z3Buemtndmpzdnd3Z25vaGpyLnN1cGFiYXNlLmNvL2F1dGgvdjEiLCJzdWIiOiI1OTlkMzk0YS1lNjc0LTRhOTUtOWUxNi02MGQ0NzEyYWVmYmQiLCJhdWQiOiJhdXRoZW50aWNhdGVkIiwiZXhwIjoxNzU4OTEwMTcwLCJpYXQiOjE3NTg5MDY1NzAsImVtYWlsIjoiamoudHNhby5tYWlsQGdtYWlsLmNvbSIsInBob25lIjoiIiwiYXBwX21ldGFkYXRhIjp7InByb3ZpZGVyIjoiZW1haWwiLCJwcm92aWRlcnMiOlsiZW1haWwiXX0sInVzZXJfbWV0YWRhdGEiOnsiZW1haWwiOiJqai50c2FvLm1haWxAZ21haWwuY29tIiwiZW1haWxfdmVyaWZpZWQiOnRydWUsInBob25lX3ZlcmlmaWVkIjpmYWxzZSwic3ViIjoiNTk5ZDM5NGEtZTY3NC00YTk1LTllMTYtNjBkNDcxMmFlZmJkIn0sInJvbGUiOiJhdXRoZW50aWNhdGVkIiwiYWFsIjoiYWFsMSIsImFtciI6W3sibWV0aG9kIjoicGFzc3dvcmQiLCJ0aW1lc3RhbXAiOjE3NTg1OTE4MTZ9XSwic2Vzc2lvbl9pZCI6ImE1YTJmZThlLWNlNDktNDI4MC1hY2Y5LWRmYjljYWIwODlkNCIsImlzX2Fub255bW91cyI6ZmFsc2V9.7M2ltn_LgW7FbiJpxr7HCAfRyMJDCWpPORuzV5gkF40"

sb = get_supabase_client(TEST_ACCESS_TOKEN)
user_id = get_current_user_id(sb, TEST_ACCESS_TOKEN)

qdrant = connect_qdrant(api_key=QDRANT_API_KEY, endpoint=QDRANT_ENDPOINT)

embed_model = load_sentence_model()
bm25_models, bm25_vocabs = load_bm25_files()
query_encoder = Encoder(embed_model, bm25_models, bm25_vocabs)

cross_encoder = load_cross_encoder()
base_retriever = BaseRetriever(
    client=qdrant,
    movie_collection=QDRANT_MOVIE_COLLECTION_NAME,
    tv_collection=QDRANT_TV_COLLECTION_NAME,
    dense_vector_name="dense_vector",
    sparse_vector_name="sparse_vector",
)
pipeline = FirstRecommendPipeline(base_retriever, ce_model=cross_encoder, rrf_k=60)


# ===== [TEST] Build and Write Tasete Vector to DB ===== 

media_type = "movie"

signals = get_user_signals(sb, user_id, media_type=media_type)

EmbedMap = Mapping[MediaId, NDArray[np.float32]]

def get_item_embeddings(ids: Sequence[MediaId]) -> EmbedMap:
    return load_embeddings_qdrant(qdrant, media_type, ids)

vec, debug = build_taste_vector(
    user=signals,
    get_item_embeddings=get_item_embeddings,
    vibe_centroids={},
    keyword_centroids={},
    params=BuildParams(dim=768),
)

upsert_taste_profile(sb, user_id, media_type, vec, debug)


# ===== [TEST] Fetch User Context and Make First Recs =====


def bm25_query_from_signals(genres_inc, keywords_inc):
    # 1) collect and weight terms
    # vibe_tags_weighted: list[("slow-burn", 0.9), ("psychological", 0.8), ...]
    def reps(w):
        # map w in [0,1] to repetitions; tune as you like
        return 1 if w < 0.4 else 2 if w < 0.6 else 3 if w < 0.8 else 4

    bag = []
    # light boost for included genres (don’t add too many)
    for g in (genres_inc or []):
        bag += [g] * 2

    for k in (keywords_inc or []):
        bag += [k] * 3

    # 3) collapse back to a short “query doc”
    return " ".join(bag[:60])  # guardrail on length


def summarize_ranking(ranking: List[Candidate], top_k: int=20):
    for idx, r in enumerate(ranking[:top_k], start=1):
        print (f"#{idx}: Title: {r.payload['title']} | Dense Score: {r.dense_score} | Sparse Score: {r.sparse_score} | Rating: {r.payload['vote_average']} | Popularity: {r.payload['popularity']}")


media_type = "movie"

user_context = fetch_user_taste_context(sb, user_id)

bm25_tags = bm25_query_from_signals(user_context.signals.genres_include, user_context.signals.keywords_include)

dense_vec = user_context.taste_vector
sparse_vec = query_encoder.encode_sparse(bm25_tags, media_type)

first_recs, _ = pipeline.run(media_type=media_type, dense_vec=dense_vec, sparse_vec=sparse_vec, sparse_depth=200, weights={"dense": 0.45, "sparse": 0.15, "rating": 0.20, "popularity": 0.10})

summarize_ranking(first_recs)


# ===== Test Input Interactions =====

res = load_metadata_qdrant(qdrant, media_type, [11])
res.get(11).get('title')

interactions = load_metadata_qdrant(qdrant, media_type, [i.media_id for i in signals.interactions if i.kind in {"like", "love"}])

user_context.taste_vector
user_context.signals.genres_include
user_context.signals. keywords_include
user_context.signals.interactions

signals.positive_interactions()

pos_int = load_metadata_qdrant(qdrant, media_type, [i.media_id for i in signals.positive_interactions()])
for k, v in pos_int.items():
    print (v.get("title", ""))
    
    
#1: Title: The Curious Case of Benjamin Button | Dense Score: 0.40896344 | Sparse Score: 60.849274 | Rating: 7.594 | Popularity: 9.287
#2: Title: Whiplash | Dense Score: 0.35855168 | Sparse Score: None | Rating: 8.377 | Popularity: 17.6069
#3: Title: Her | Dense Score: 0.37067655 | Sparse Score: None | Rating: 7.847 | Popularity: 8.515
#4: Title: Fight Club | Dense Score: 0.3863207 | Sparse Score: None | Rating: 8.4 | Popularity: 20.3297
#5: Title: The Great Gatsby | Dense Score: 0.37500882 | Sparse Score: None | Rating: 7.361 | Popularity: 7.6377
#6: Title: The Prestige | Dense Score: 0.3986895 | Sparse Score: None | Rating: 8.204 | Popularity: 15.4664
#7: Title: Sunset Boulevard | Dense Score: 0.3489128 | Sparse Score: None | Rating: 8.292 | Popularity: 3.9608
#8: Title: Logan | Dense Score: 0.36030138 | Sparse Score: None | Rating: 7.82 | Popularity: 10.3345
#9: Title: 8½ | Dense Score: 0.38152653 | Sparse Score: None | Rating: 8.1 | Popularity: 3.2041
#10: Title: The Danish Girl | Dense Score: 0.39892426 | Sparse Score: None | Rating: 7.567 | Popularity: 3.42
#11: Title: Mr. Nobody | Dense Score: 0.3837769 | Sparse Score: None | Rating: 7.805 | Popularity: 3.505
#12: Title: Poor Things | Dense Score: 0.3440053 | Sparse Score: None | Rating: 7.671 | Popularity: 11.5659
#13: Title: Blade Runner | Dense Score: 0.31622797 | Sparse Score: 72.68185 | Rating: 7.942 | Popularity: 10.2113
#14: Title: Interview with the Vampire | Dense Score: 0.33603358 | Sparse Score: None | Rating: 7.4 | Popularity: 7.77
#15: Title: Eternal Sunshine of the Spotless Mind | Dense Score: 0.2949273 | Sparse Score: 61.944168 | Rating: 8.093 | Popularity: 12.3963
#16: Title: A Beautiful Mind | Dense Score: 0.31089553 | Sparse Score: 46.972534 | Rating: 7.856 | Popularity: 6.1061
#17: Title: Only Lovers Left Alive | Dense Score: 0.34301126 | Sparse Score: None | Rating: 7.213 | Popularity: 2.7544
#18: Title: The Father | Dense Score: 0.2943558 | Sparse Score: 55.779892 | Rating: 8.109 | Popularity: 3.9571
#19: Title: Leaving Las Vegas | Dense Score: 0.33776125 | Sparse Score: None | Rating: 7.251 | Popularity: 4.2452
#20: Title: Finch | Dense Score: 0.28760812 | Sparse Score: 45.68068 | Rating: 7.833 | Popularity: 5.6205