from typing import Sequence, Dict, Union, List, Any
import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

def load_embeddings_qdrant(
    client: QdrantClient,
    collection: str,
    ids: Sequence[int],
    vector_name: str = "dense_vector"
) -> Dict[int, np.ndarray]:
    if not ids:
        return {}
    res, _ = client.scroll(
        collection_name=collection,
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