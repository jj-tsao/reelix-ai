from __future__ import annotations

from typing import Any, Optional

import numpy as np

from reelix_core.config import EMBEDDING_MODEL

TABLE = "user_taste_profile"


async def upsert_taste_profile(
    sb: Any,
    user_id: str,
    media_type: str,
    vec: np.ndarray,
    debug: dict[str, Any],
    *,
    model_name: str = EMBEDDING_MODEL,
    dim: int = 768,
) -> None:
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


async def fetch(sb: Any, user_id: str) -> Optional[dict[str, Any]]:
    res = sb.postgrest.table(TABLE).select("*").eq("user_id", user_id).single().execute()
    data = getattr(res, "data", None)
    return data if data else None
