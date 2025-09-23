from __future__ import annotations
from datetime import datetime, timezone
from typing import Dict, Mapping, Sequence

import numpy as np
from numpy.typing import NDArray
from qdrant_client import QdrantClient

from app.repositories.taste_profile_store import upsert_taste_profile
from reelix_retrieval.embedding_loader import load_embeddings_qdrant
from reelix_user.taste_profile import build_taste_vector
from reelix_user.types import BuildParams, Interaction, MediaId, UserSignals


# 1) fetch user signals from DB
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

    rows: list[dict]
    if hasattr(pg, "fetchrow"):
        prefs_row = await pg.fetchrow(
            """
          select coalesce(genres_include,'{}') as genres, coalesce(keywords_include,'{}') as kws
          from public.user_preferences where user_id=$1
        """,
            user_id,
        )
        async_rows = await pg.fetch(
            f"""
          select media_type, media_id, event_type, {timestamp_key}
          from public.user_interactions
          where user_id=$1
          order by {timestamp_key} desc
          limit 500
        """,
            user_id,
        )
        prefs_dict = dict(prefs_row) if prefs_row else {}
        rows = [dict(r) for r in async_rows]
        genres = list(prefs_dict.get("genres") or [])
        keywords = list(prefs_dict.get("kws") or [])
    else:
        try:
            pref_res = (
                pg.postgrest.table("user_preferences")
                .select("genres_include, keywords_include")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            pref_rows = getattr(pref_res, "data", None)
            prefs = pref_rows[0] if pref_rows else {}
        except Exception:
            prefs = {}
        genres = list(prefs.get("genres_include") or [])
        keywords = list(prefs.get("keywords_include") or [])

        try:
            inter_res = (
                pg.postgrest.table("user_interactions")
                .select(f"media_type, media_id, event_type, {timestamp_key}")
                .eq("user_id", user_id)
                .order(timestamp_key, desc=True)
                .limit(500)
                .execute()
            )
            rows = list(getattr(inter_res, "data", []) or [])
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
        genres_include=genres,
        keywords_include=keywords,
        interactions=interactions,
    )


# 2) vibe & keyword centroids loader
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
