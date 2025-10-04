from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer
from supabase import Client, create_client

from app.deps.deps import SupabaseCreds, get_supabase_creds

security = HTTPBearer(auto_error=False)


def get_optional_bearer(credentials=Depends(security)) -> Optional[str]:
    # Returns None if no Authorization header
    return credentials.credentials if credentials else None


def get_supabase_client_optional(
    user_token: Optional[str] = Depends(get_optional_bearer),
    creds: SupabaseCreds = Depends(get_supabase_creds),
) -> Client:
    """
    Returns a Supabase client. If user_token is present, it is user-scoped (RLS sees auth.uid()).
    If not, itis an anon client (no postgrest.auth()) for public reads only.
    """
    try:
        client: Client = create_client(creds.url, creds.api_key)
        if user_token:
            client.postgrest.auth(user_token)
        return client
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Supabase init failed: {exc}",
        )


def get_optional_user_id(
    client: Client = Depends(get_supabase_client_optional),
    user_token: Optional[str] = Depends(get_optional_bearer),
) -> Optional[str]:
    if not user_token:
        return None
    try:
        resp = client.auth.get_user(user_token)
        user = getattr(resp, "user", None) or getattr(resp, "data", None)
        return (getattr(user, "id", None) or (user or {}).get("id")) or None
    except Exception:
        # Treat failures as anonymous
        return None
