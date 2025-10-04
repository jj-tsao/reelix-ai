from __future__ import annotations
from typing import Dict, Mapping, Sequence

import numpy as np
from numpy.typing import NDArray
from qdrant_client import QdrantClient

from app.repositories.taste_profile_store import fetch_user_signals, upsert_taste_profile
from reelix_retrieval.embedding_loader import load_embeddings_qdrant
from reelix_user.taste_profile import build_taste_vector
from reelix_core.types import (
    BuildParams,
    MediaId,
)


def load_vibe_centroids() -> Dict[str, np.ndarray]:
    # TODO: read from a .npz/.json or module you produce at training time
    return {}


def load_keyword_centroids() -> Dict[str, np.ndarray]:
    # TODO: read from a .npz/.json or module you produce at training time
    return {}


EmbedMap = Mapping[MediaId, NDArray[np.float32]]


async def rebuild_and_store(
    sb,
    user_id: str,
    qdrant: QdrantClient,
    media_type: str = "movie",
    params: BuildParams = BuildParams(dim=768),
):
    signals = await fetch_user_signals(sb, user_id, media_type=media_type)

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
    await upsert_taste_profile(sb, user_id, media_type, vec, debug)
    return vec, debug
