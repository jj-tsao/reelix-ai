from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from pydantic_settings import BaseSettings, SettingsConfigDict


class SupabaseSettings(BaseSettings):
    supabase_url: str
    supabase_anon_key: str
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = SupabaseSettings()  # Loaded once; env vars required at runtime


def require_bearer_token(authorization: Optional[str] = Header(None)) -> str:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization header")
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Authorization header format")
    return parts[1].strip()


def get_supabase_client(user_token: str = Depends(require_bearer_token)):
    """Return a Supabase client authorized as the end user.
    Authenticate PostgREST with the user's JWT so that RLS policies (auth.uid()) are enforced server-side. 
    Never use a service role for these profile routes.
    """
    try:
        # Lazy import to avoid import-time failures during tooling
        from supabase import create_client, Client  # type: ignore

        client: Client = create_client(settings.supabase_url, settings.supabase_anon_key)
        # Ensure all downstream requests carry the user's JWT (RLS enforced)
        client.postgrest.auth(user_token)
        # Align other clients as well (storage/realtime) if ever used
        try:
            client.storage.auth(user_token)
        except Exception:
            pass
        try:
            client.realtime.auth(user_token)
        except Exception:
            pass
        return client
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - protects from missing deps at dev time
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Supabase init failed: {exc}")


def get_current_user_id(
    client=Depends(get_supabase_client), user_token: str = Depends(require_bearer_token)
) -> str:
    """Fetch the current user id (UUID) from GoTrue using the user's token."""
    try:
        # gotrue-python expects the token to be passed explicitly
        resp = client.auth.get_user(user_token)
        user = getattr(resp, "user", None) or getattr(resp, "data", None)
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
        user_id = getattr(user, "id", None) or user.get("id")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user in token")
        return user_id
    except HTTPException:
        raise
    except Exception as exc:
        # If GoTrue call fails, surface as auth error (most common case)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Failed to resolve user: {exc}")
