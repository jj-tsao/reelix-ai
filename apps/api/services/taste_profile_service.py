from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Dict, Mapping, Sequence

import numpy as np
from numpy.typing import NDArray
from qdrant_client import QdrantClient

from app.repositories.taste_profile_store import upsert_taste_profile
from reelix_retrieval.embedding_loader import load_embeddings_qdrant
from reelix_user.taste_profile import build_taste_vector
from reelix_user.types import BuildParams, Interaction, MediaId, UserSignals


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


async def get_user_signals(pg, user_id: str) -> UserSignals:
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


# Collect taste vector and preference metadata for recommendaitons.
async def fetch_user_taste_context(
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


def load_vibe_centroids() -> Dict[str, np.ndarray]:
    # TODO: read from a .npz/.json or module you produce at training time
    return {}


def load_keyword_centroids() -> Dict[str, np.ndarray]:
    # TODO: read from a .npz/.json or module you produce at training time
    return {}


EmbedMap = Mapping[MediaId, NDArray[np.float32]]


async def rebuild_and_store(
    pg,
    user_id: str,
    qdrant: QdrantClient,
    media_type: str = "movie",
    params: BuildParams = BuildParams(dim=768),
):
    signals = await get_user_signals(pg, user_id)

    def get_item_embeddings(ids: Sequence[MediaId]) -> EmbedMap:
        return load_embeddings_qdrant(qdrant, media_type, ids)

    vibe_centroids = load_vibe_centroids()
    keyword_centroids = load_keyword_centroids()

    vec, debug = build_taste_vector(
        user=signals,
        get_item_embeddings=get_item_embeddings,
        vibe_centroids=vibe_centroids,
        keyword_centroids=keyword_centroids,
        params=params,
    )
    await upsert_taste_profile(pg, user_id, media_type, vec, debug)
    return vec, debug
