from typing import Any, Callable, TYPE_CHECKING, cast
from dataclasses import dataclass

from fastapi import HTTPException, Request, status
from qdrant_client import QdrantClient

if TYPE_CHECKING:
    from reelix_recommendation.recommend import RecommendPipeline


def _get_state_attr(request: Request, name: str, error_detail: str) -> Any:
    value = getattr(request.app.state, name, None)
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_detail,
        )
    return value


def get_settings(request: Request) -> Any:
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Settings not initialized",
        )
    return settings


def get_qdrant(request: Request) -> QdrantClient:
    return cast(
        QdrantClient,
        _get_state_attr(request, "qdrant", "QDRANT client not initialized"),
    )


def get_recommend_pipeline(request: Request) -> "RecommendPipeline":
    return cast(
        "RecommendPipeline",
        _get_state_attr(
            request,
            "recommend_pipeline",
            "Recommendation pipeline not initialized",
        ),
    )


def get_interactive_stream_fn(request: Request) -> Callable:
    fn = getattr(request.app.state, "interactive_stream_fn", None)
    if not callable(fn):
        raise HTTPException(status_code=503, detail="Recommendation service is initializing.")
    return fn


@dataclass(frozen=True)
class SupabaseCreds:
    url: str
    api_key: str

def get_supabase_creds(request: Request) -> SupabaseCreds:
    return SupabaseCreds(
        url=getattr(request.app.state, "supabase_url", ""),
        api_key=getattr(request.app.state, "supabase_api_key", ""),
    )
