from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, status

from ..schemas import (
    InteractionsPayload,
    PreferencesUpdate,
    SubscriptionsPayload,
)
from ..supabase_client import get_current_user_id, get_supabase_client


router = APIRouter(prefix="/profile", tags=["profile"])


@router.post("/preferences")
def upsert_preferences(
    prefs: PreferencesUpdate,
    client=Depends(get_supabase_client),
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """Upsert current user's preferences into public.user_preferences.

    RLS ensures only the owner can upsert/select. We explicitly set user_id from the token.
    """
    row = {k: v for k, v in prefs.model_dump(exclude_none=True).items()}
    row["user_id"] = user_id
    try:
        # Upsert on primary key (user_id)
        res = (
            client.table("user_preferences")
            .upsert(row, on_conflict="user_id")
            .select("*")
            .execute()
        )
        data = getattr(res, "data", None) or getattr(res, "json", None)
        if isinstance(data, list):
            data = data[0] if data else None
        if not data:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Upsert failed")
        return data
    except Exception as exc:
        _raise_http_from_supabase(exc)


@router.post("/subscriptions")
def upsert_subscriptions(
    payload: SubscriptionsPayload,
    client=Depends(get_supabase_client),
    user_id: str = Depends(get_current_user_id),
) -> List[Dict[str, Any]]:
    """Upsert user's streaming subscriptions into public.user_subscriptions.

    Uses composite unique key (user_id, provider_id). Soft-delete is via active=false.
    """
    rows = [
        {"user_id": user_id, "provider_id": s.provider_id, "active": True if s.active is None else s.active}
        for s in payload.subscriptions
    ]
    try:
        res = (
            client.table("user_subscriptions")
            .upsert(rows, on_conflict="user_id,provider_id")
            .select("*")
            .execute()
        )
        data = getattr(res, "data", None) or getattr(res, "json", None)
        if not data:
            return []
        return data
    except Exception as exc:
        _raise_http_from_supabase(exc)


@router.post("/interactions")
def insert_interactions(
    payload: InteractionsPayload,
    client=Depends(get_supabase_client),
    user_id: str = Depends(get_current_user_id),
) -> List[Dict[str, Any]]:
    """Append user interactions to public.user_interactions (no update/delete)."""
    rows = []
    for it in payload.interactions:
        row = {
            "user_id": user_id,
            "media_type": it.media_type,
            "tmdb_id": it.tmdb_id,
            "event_type": it.event_type,
        }
        if it.weight is not None:
            row["weight"] = it.weight
        if it.context_json is not None:
            row["context_json"] = it.context_json
        if it.occurred_at is not None:
            row["occurred_at"] = it.occurred_at
        rows.append(row)
    try:
        res = client.table("user_interactions").insert(rows).select("*").execute()
        data = getattr(res, "data", None) or getattr(res, "json", None)
        if not data:
            return []
        return data
    except Exception as exc:
        _raise_http_from_supabase(exc)


def _raise_http_from_supabase(exc: Exception) -> None:
    """Normalize Supabase errors into HTTP exceptions."""
    # postgrest-py typically raises APIError with .message and .code
    detail = str(getattr(exc, "message", None) or exc)
    code = getattr(exc, "code", None)
    # Map common authorization/rls failures to 403 per requirements
    if code in ("PGRST301", "PGRST302") or "permission denied" in detail.lower():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden/ownership")
    # Constraint violations surface as 400 to clients
    if "check constraint" in detail.lower() or "violates" in detail.lower():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
    # Fallback to 500
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=detail)
