from __future__ import annotations
from typing import Dict, Sequence, Mapping
import numpy as np
from numpy.typing import NDArray
from qdrant_client import QdrantClient


from reelix_user.types import UserSignals, Interaction, BuildParams, MediaId
from reelix_user.taste_profile import build_taste_vector
from reelix_retrieval.embedding_loader import load_embeddings_qdrant
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
      select media_type, media_id, event_type, created_at
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
                media_type=str(r["media_type"]),
                media_id=int(r["media_id"]),
                kind=r["event_type"],
                ts=r["created_at"],
            )
            for r in rows
        ],
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
    collection: str,
    params: BuildParams = BuildParams(dim=768),
):
    signals = await get_user_signals(pg, user_id)

    def get_item_embeddings(ids: Sequence[MediaId]) -> EmbedMap:
        return load_embeddings_qdrant(qdrant, collection, ids)

    vibe_centroids = load_vibe_centroids()
    keyword_centroids = load_keyword_centroids()

    vec, debug = build_taste_vector(
        user=signals,
        get_item_embeddings=get_item_embeddings,
        vibe_centroids=vibe_centroids,
        keyword_centroids=keyword_centroids,
        params=params,
    )
    await taste_store.upsert(pg, user_id, vec, debug)
    return vec, debug