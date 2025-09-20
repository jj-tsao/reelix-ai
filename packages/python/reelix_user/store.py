from __future__ import annotations
from typing import Any, Optional
import numpy as np

TABLE = "user_taste_profile"

async def upsert(sb, user_id: str, vec: np.ndarray, debug: dict[str, Any]):
    payload = {
        "user_id": user_id,
        "dense": vec.tolist(),  # pgvector accepts float[] via PostgREST
        "positive_n": int(debug["pos_count"]),
        "negative_n": int(debug["neg_count"]),
        "params": debug["params"],
    }
    # Prefer upsert on PK; relies on RLS to scope to the current user
    # PostgREST python client is sync; supabase-py wraps it in sync calls.
    # Use `await sb.postgrest.table(...).upsert(...).execute()` if your client supports async,
    # otherwise call it sync in a thread if needed. Most apps just call it sync.
    res = sb.postgrest.table(TABLE).upsert(payload).execute()
    return res.data

async def fetch(sb, user_id: str) -> Optional[dict[str, Any]]:
    res = sb.postgrest.table(TABLE).select("*").eq("user_id", user_id).single().execute()
    return res.data if getattr(res, "data", None) else None
