from __future__ import annotations

from typing import Any, Optional

import numpy as np


TABLE = "user_taste_profile"


async def upsert(sb: Any, user_id: str, vec: np.ndarray, debug: dict[str, Any]):
    payload = {
        "user_id": user_id,
        "dense": vec.tolist(),
        "positive_n": int(debug["pos_count"]),
        "negative_n": int(debug["neg_count"]),
        "params": debug["params"],
    }
    res = sb.postgrest.table(TABLE).upsert(payload).execute()
    return getattr(res, "data", None)


async def upsert_taste_profile(sb: Any, user_id: str, media_type: str, model_name: str, vec: np.ndarray, debug: dict[str, Any], dim=768):
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


async def fetch(sb: Any, user_id: str) -> Optional[dict[str, Any]]:
    res = sb.postgrest.table(TABLE).select("*").eq("user_id", user_id).single().execute()
    data = getattr(res, "data", None)
    return data if data else None

