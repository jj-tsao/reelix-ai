import os

from dotenv import find_dotenv, load_dotenv

from reelix_retrieval.embedding_loader import load_embeddings_qdrant
from reelix_user.taste_profile import build_taste_vector
from reelix_retrieval.vectorstore import connect_qdrant
from reelix_user.types import UserSignals, Interaction, BuildParams, MediaId
from reelix_core.config import EMBEDDING_MODEL
from typing import Optional, Mapping, Sequence, Any
from numpy.typing import NDArray
import numpy as np
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, status
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv(find_dotenv(), override=False)

QDRANT_API_KEY = str(os.getenv("QDRANT_API_KEY"))
QDRANT_ENDPOINT = str(os.getenv("QDRANT_ENDPOINT"))
SUPABASE_URL = str(os.getenv("SUPABASE_URL"))
SUPABASE_ANON_KEY = str(os.getenv("SUPABASE_ANON_KEY"))

if (
    not QDRANT_API_KEY
    or not QDRANT_ENDPOINT
    or not SUPABASE_URL
    or not SUPABASE_ANON_KEY
):
    raise ValueError("Missing api key or endpoint.")

class SupabaseSettings(BaseSettings):
    supabase_url: str = Field(default_factory=lambda: os.getenv("SUPABASE_URL", ""))
    supabase_anon_key: str = Field(default_factory=lambda: os.getenv("SUPABASE_ANON_KEY", ""))
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = SupabaseSettings()  # Loaded once; env vars required at runtime


def require_bearer_token(authorization: Optional[str] = Header(None)) -> str:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Authorization header format")
    return token.strip()


def get_supabase_client(user_token: str = Depends(require_bearer_token)):
    """Return a Supabase client authorized as the end user (DB calls go through PostgREST with user JWT)."""
    try:
        from supabase import create_client, Client  # type: ignore
        client: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

        # Critical: attach the user's JWT for DB calls so RLS (auth.uid()) is enforced.
        client.postgrest.auth(user_token)

        return client
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Supabase init failed: {exc}")


def get_current_user_id(
    client=Depends(get_supabase_client), user_token: str = Depends(require_bearer_token)
) -> str:
    """Fetch the current user id (UUID) from GoTrue using the user's token."""
    try:
        # gotrue-python expects the token to be passed explicitly
        resp = client.auth.get_user(user_token)
        user = getattr(resp, "user", None) or getattr(resp, "data", None)
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
        user_id = getattr(user, "id", None) or user.get("id")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user in token")
        return user_id
    except HTTPException:
        raise
    except Exception as exc:
        # If GoTrue call fails, surface as auth error (most common case)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Failed to resolve user: {exc}")

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

def get_user_signals_via_supabase(pg, user_id: str) -> UserSignals:
    pref_res = pg.postgrest.table("user_preferences") \
        .select("genres_include, keywords_include") \
        .eq("user_id", user_id) \
        .single() \
        .execute()
    prefs = pref_res.data or {}

    inter_res = pg.postgrest.table("user_interactions") \
        .select("media_type, media_id, event_type, occurred_at") \
        .eq("user_id", user_id) \
        .order("occurred_at", desc=True) \
        .limit(500) \
        .execute()
    rows = inter_res.data or []

    def parse_ts(raw: str) -> datetime:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))

    return UserSignals(
        genres_include=list(prefs.get("genres_include") or []),
        keywords_include=list(prefs.get("keywords_include") or []),
        interactions=[
            Interaction(
                media_type=str(r["media_type"]),
                media_id=int(r["media_id"]),
                kind=r["event_type"],
                ts=ts,
            )
            for r in rows
            if (ts := _ensure_ts(r["occurred_at"])) is not None
        ],
    )

TABLE = "user_taste_profile"

def upsert_taste_profile(sb: Any, user_id: str, media_type: str, vec: np.ndarray, debug: dict[str, Any], model_name: str = EMBEDDING_MODEL, dim=768):
    payload = {
        "user_id": user_id,
        "media_type": media_type,
        "model_name": model_name,
        "dim": dim,
        "dense": vec.tolist(),                 # pgvector via PostgREST accepts float array
        "positive_n": int(debug["pos_count"]),
        "negative_n": int(debug["neg_count"]),
        "params": debug["params"],
        "last_built_at": "now()"
    }
    sb.postgrest.table(TABLE).upsert(payload).execute()

ACCESS_TOKEN = "eyJhbGciOiJIUzI1NiIsImtpZCI6IndVTWNiVm9BM253TU9yMTEiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJodHRwczovL3l5Z3Buemtndmpzdnd3Z25vaGpyLnN1cGFiYXNlLmNvL2F1dGgvdjEiLCJzdWIiOiI1OTlkMzk0YS1lNjc0LTRhOTUtOWUxNi02MGQ0NzEyYWVmYmQiLCJhdWQiOiJhdXRoZW50aWNhdGVkIiwiZXhwIjoxNzU4NjU0NDg4LCJpYXQiOjE3NTg2NTA4ODgsImVtYWlsIjoiamoudHNhby5tYWlsQGdtYWlsLmNvbSIsInBob25lIjoiIiwiYXBwX21ldGFkYXRhIjp7InByb3ZpZGVyIjoiZW1haWwiLCJwcm92aWRlcnMiOlsiZW1haWwiXX0sInVzZXJfbWV0YWRhdGEiOnsiZW1haWwiOiJqai50c2FvLm1haWxAZ21haWwuY29tIiwiZW1haWxfdmVyaWZpZWQiOnRydWUsInBob25lX3ZlcmlmaWVkIjpmYWxzZSwic3ViIjoiNTk5ZDM5NGEtZTY3NC00YTk1LTllMTYtNjBkNDcxMmFlZmJkIn0sInJvbGUiOiJhdXRoZW50aWNhdGVkIiwiYWFsIjoiYWFsMSIsImFtciI6W3sibWV0aG9kIjoicGFzc3dvcmQiLCJ0aW1lc3RhbXAiOjE3NTg1OTE4MTZ9XSwic2Vzc2lvbl9pZCI6ImE1YTJmZThlLWNlNDktNDI4MC1hY2Y5LWRmYjljYWIwODlkNCIsImlzX2Fub255bW91cyI6ZmFsc2V9.j33SFgMoKyynKxQS84vlkOtehM3_UKSD92MCF1lRuaI"


sb = get_supabase_client(ACCESS_TOKEN)
user_id = get_current_user_id(sb, ACCESS_TOKEN)

signals = get_user_signals_via_supabase(sb, user_id)

qdrant = connect_qdrant(api_key=QDRANT_API_KEY, endpoint=QDRANT_ENDPOINT)

embds = load_embeddings_qdrant(qdrant, "movie", [11, 12])
media_type = "movie"

EmbedMap = Mapping[MediaId, NDArray[np.float32]]

def get_item_embeddings(ids: Sequence[MediaId]) -> EmbedMap:
    return load_embeddings_qdrant(qdrant, media_type, ids)

vec, debug = build_taste_vector(
        user=signals,
        get_item_embeddings=get_item_embeddings,
        vibe_centroids={},
        keyword_centroids={},
        params = BuildParams(dim=768),
    )

upsert_taste_profile(sb, user_id, media_type, vec, debug)