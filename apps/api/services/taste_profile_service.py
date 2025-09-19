from __future__ import annotations
from typing import Dict
import numpy as np
from qdrant_client import QdrantClient

from reelix_user.types import UserSignals, Interaction, BuildParams
from reelix_user.taste_profile import build_taste_vector
from reelix_user.qdrant_items import load_item_embeddings_qdrant
from reelix_user import store as taste_store


# 1) fetch user signals from DB
async def get_user_signals(pg, user_id: str) -> UserSignals:
    prefs = await pg.fetchrow(
        """
      select coalesce(genres_include,'{}') as genres, coalesce(keywords_include,'{}') as kws
      from public.user_preferences where user_id=$1
    """,
        user_id,
    )
    rows = await pg.fetch(
        """
      select media_id, interaction_type, created_at
      from public.user_interactions
      where user_id=$1
      order by created_at desc
      limit 500
    """,
        user_id,
    )
    return UserSignals(
        genres_include=list(prefs["genres"] or []),
        keywords_include=list(prefs["kws"] or []),
        interactions=[
            Interaction(
                media_id=str(r["media_id"]),
                kind=r["interaction_type"],
                ts=r["created_at"],
            )
            for r in rows
        ],
    )


# 2) vibe centroids loader (stub → wire to your cache file/artifact)
def load_vibe_centroids() -> Dict[str, np.ndarray]:
    # TODO: read from a .npz/.json or module you produce at training time
    return {}


async def rebuild_and_store(
    pg,
    user_id: str,
    qdrant: QdrantClient,
    collection: str,
    text_embedder,  # callable: list[str] -> list[np.ndarray]
    params: BuildParams = BuildParams(dim=768),
):
    signals = await get_user_signals(pg, user_id)
    get_item_embeddings = lambda ids: load_item_embeddings_qdrant(
        qdrant, collection, ids, "dense_vector"
    )
    vibe_centroids = load_vibe_centroids()

    vec, debug = build_taste_vector(
        user=signals,
        get_item_embeddings=get_item_embeddings,
        embed_texts=text_embedder,
        vibe_centroids=vibe_centroids,
        params=params,
    )
    await taste_store.upsert(pg, user_id, vec, debug)
    return vec, debug
