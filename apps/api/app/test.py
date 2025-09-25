import os
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence

import numpy as np
from dotenv import find_dotenv, load_dotenv
from fastapi import Depends, Header, HTTPException, status
from numpy.typing import NDArray
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from reelix_core.config import EMBEDDING_MODEL
from reelix_retrieval.embedding_loader import load_embeddings_qdrant
from reelix_retrieval.vectorstore import connect_qdrant
from reelix_user.taste_profile import build_taste_vector
from reelix_user.types import BuildParams, Interaction, MediaId, UserSignals


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


def get_user_signals(pg, user_id: str) -> UserSignals:
    timestamp_key = "occurred_at"

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
        inter_res = (
            pg.postgrest.table("user_interactions")
            .select(f"media_type, media_id, event_type, {timestamp_key}")
            .eq("user_id", user_id)
            .order(timestamp_key, desc=True)
            .limit(500)
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
        if (ts := _ensure_ts(row.get(timestamp_key) or row.get("created_at")))
        is not None
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

@dataclass
class UserTasteContext:
    taste_vector: list[float] | None
    positive_n: int | None
    negative_n: int | None
    last_built_at: datetime | None
    genres_include: list[str]
    genres_exclude: list[str]
    keywords_include: list[str]
    keywords_exclude: list[str]
    active_subscriptions: list[int]
    provider_filter_mode: str | None

def fetch_user_taste_context(
    sb,
    user_id: str,
    media_type: str = "movie",
) -> UserTasteContext:
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
        if isinstance(taste_data, dict):
            taste_row = taste_data
        else:
            taste_row = taste_data[0] if taste_data else None
    except Exception:
        taste_row = None

    try:
        prefs_res = (
            sb.postgrest.table("user_preferences")
            .select(
                "genres_include, genres_exclude, keywords_include, keywords_exclude"
            )
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        prefs_rows = getattr(prefs_res, "data", None) or []
        prefs_row = prefs_rows[0] if prefs_rows else {}
    except Exception:
        prefs_row = {}

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

    dense = (taste_row or {}).get("dense") if taste_row else None
    taste_vector: list[float] | None = None
    if isinstance(dense, list):
        taste_vector = [float(v) for v in dense]
    elif isinstance(dense, str):
        raw = dense.strip()
        try:
            # PostgREST often returns pgvector as JSON array string
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            # Fallback for Postgres "{...}" array format
            trimmed = raw.strip("{}")
            items = [i for i in trimmed.split(",") if i]
            try:
                parsed = [float(i) for i in items]
            except ValueError:
                parsed = None
        if isinstance(parsed, list):
            taste_vector = [float(v) for v in parsed]

    raw_positive = (taste_row or {}).get("positive_n") if taste_row else None
    positive_n = int(raw_positive) if raw_positive is not None else None
    raw_negative = (taste_row or {}).get("negative_n") if taste_row else None
    negative_n = int(raw_negative) if raw_negative is not None else None

    return UserTasteContext(
        taste_vector=taste_vector,
        positive_n=positive_n,
        negative_n=negative_n,
        last_built_at=_ensure_ts((taste_row or {}).get("last_built_at"))
        if taste_row
        else None,
        genres_include=list(prefs_row.get("genres_include") or []),
        genres_exclude=list(prefs_row.get("genres_exclude") or []),
        keywords_include=list(prefs_row.get("keywords_include") or []),
        keywords_exclude=list(prefs_row.get("keywords_exclude") or []),
        active_subscriptions=[
            int(row["provider_id"])
            for row in subs_rows
            if row.get("provider_id") is not None
        ],
        provider_filter_mode=settings_row.get("provider_filter_mode") or "SELECTED",
    )



# ===== Dependencies ===== 

load_dotenv(find_dotenv(), override=False)

QDRANT_API_KEY = str(os.getenv("QDRANT_API_KEY"))
QDRANT_ENDPOINT = str(os.getenv("QDRANT_ENDPOINT"))
SUPABASE_URL = str(os.getenv("SUPABASE_URL"))
SUPABASE_ANON_KEY = str(os.getenv("SUPABASE_ANON_KEY"))

TEST_ACCESS_TOKEN = "eyJhbGciOiJIUzI1NiIsImtpZCI6IndVTWNiVm9BM253TU9yMTEiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJodHRwczovL3l5Z3Buemtndmpzdnd3Z25vaGpyLnN1cGFiYXNlLmNvL2F1dGgvdjEiLCJzdWIiOiI1OTlkMzk0YS1lNjc0LTRhOTUtOWUxNi02MGQ0NzEyYWVmYmQiLCJhdWQiOiJhdXRoZW50aWNhdGVkIiwiZXhwIjoxNzU4ODI4ODMxLCJpYXQiOjE3NTg4MjUyMzEsImVtYWlsIjoiamoudHNhby5tYWlsQGdtYWlsLmNvbSIsInBob25lIjoiIiwiYXBwX21ldGFkYXRhIjp7InByb3ZpZGVyIjoiZW1haWwiLCJwcm92aWRlcnMiOlsiZW1haWwiXX0sInVzZXJfbWV0YWRhdGEiOnsiZW1haWwiOiJqai50c2FvLm1haWxAZ21haWwuY29tIiwiZW1haWxfdmVyaWZpZWQiOnRydWUsInBob25lX3ZlcmlmaWVkIjpmYWxzZSwic3ViIjoiNTk5ZDM5NGEtZTY3NC00YTk1LTllMTYtNjBkNDcxMmFlZmJkIn0sInJvbGUiOiJhdXRoZW50aWNhdGVkIiwiYWFsIjoiYWFsMSIsImFtciI6W3sibWV0aG9kIjoicGFzc3dvcmQiLCJ0aW1lc3RhbXAiOjE3NTg1OTE4MTZ9XSwic2Vzc2lvbl9pZCI6ImE1YTJmZThlLWNlNDktNDI4MC1hY2Y5LWRmYjljYWIwODlkNCIsImlzX2Fub255bW91cyI6ZmFsc2V9.ZZ3VeKgkzIP7bznEpDWfc4t8uPkUisK4F3Fd_Eo5p20"

sb = get_supabase_client(TEST_ACCESS_TOKEN)
user_id = get_current_user_id(sb, TEST_ACCESS_TOKEN)

qdrant = connect_qdrant(api_key=QDRANT_API_KEY, endpoint=QDRANT_ENDPOINT)


# ===== [TEST] Build and Write Tasete Vector to DB ===== 

media_type = "movie"

signals = get_user_signals(sb, user_id)

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

media_type = "movie"

user_context = fetch_user_taste_context(sb, user_id)

user_context.taste_vector
user_context.genres_include

UserTasteContext(
    taste_vector=None, 
    positive_n=25, 
    negative_n=7, 
    last_built_at=datetime.datetime(2025, 9, 25, 18, 50, 29, 794987, tzinfo=datetime.timezone.utc), 
    genres_include=['Drama', 'Romance', 'Thriller', 'Science Fiction', 'Crime'], 
    genres_exclude=[], 
    keywords_include=['Character-Driven', 'Emotional', 'Coming-of-Age', 'Heartwarming', 'Tragic Love', 'Suspenseful', 'Intense', 'Mind-Bending', 'Dystopian'], 
    keywords_exclude=[], 
    active_subscriptions=[8, 15, 9], 
    provider_filter_mode='SELECTED')
