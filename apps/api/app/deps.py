from typing import Any

from fastapi import HTTPException, Request, status
from qdrant_client import QdrantClient


def get_settings(request: Request) -> Any:
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Settings not initialized",
        )
    return settings


def get_qdrant(request: Request) -> QdrantClient:
    client = getattr(request.app.state, "qdrant", None)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="QDRANT client not initialized",
        )
    return client
