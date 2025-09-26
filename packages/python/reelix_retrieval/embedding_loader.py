from typing import Sequence, Dict, Union, List, Any
import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm
from reelix_core.config import QDRANT_MOVIE_COLLECTION_NAME, QDRANT_TV_COLLECTION_NAME

def load_embeddings_qdrant(
    client: QdrantClient,
    media_type: str,
    ids: Sequence[int],
    vector_name: str = "dense_vector"
) -> Dict[int, np.ndarray]:
    if not ids:
        return {}
    res, _ = client.scroll(
        collection_name=QDRANT_MOVIE_COLLECTION_NAME if media_type == "movie" else QDRANT_TV_COLLECTION_NAME,
        scroll_filter=qm.Filter(must=[qm.HasIdCondition(has_id=list(ids))]),
        with_payload=False,
        with_vectors=True,
        limit=len(ids),
    )
    out: Dict[int, np.ndarray] = {}
    for p in res:
        vid = int(p.id)
        if vid is None:
            continue

        # Safely access the vector
        vec: Any = p.vector
        vector_data: Union[List[float], None] = None
        
        # Check if `p.vector` is a dictionary (named vectors)
        if isinstance(vec, dict):
            vector_data = vec.get(vector_name)
        # Otherwise, assume it's a single vector (List[float])
        else:
            vector_data = vec

        if vector_data is not None:
            out[vid] = np.asarray(vector_data, dtype=np.float32)
    return out

def load_metadata_qdrant(
    client: QdrantClient,
    media_type: str,
    ids: Sequence[int],
) -> Dict[int, np.ndarray]:
    if not ids:
        return {}
    res, _ = client.scroll(
        collection_name=QDRANT_MOVIE_COLLECTION_NAME if media_type == "movie" else QDRANT_TV_COLLECTION_NAME,
        scroll_filter=qm.Filter(must=[qm.HasIdCondition(has_id=list(ids))]),
        with_payload=[
                "llm_context",
                "title",
                "popularity",
                "vote_average",
            ],
        with_vectors=False,
        limit=len(ids),
    )
    out: Dict[int, List[str]] = {}
    for p in res:
        vid = int(p.id)
        out[vid] = p.payload
    return out