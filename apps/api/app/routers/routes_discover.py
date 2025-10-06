from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from reelix_recommendation.orchestrator import orchestrate
from app.schemas import DiscoverRequest
from app.deps.deps import (
    get_recipe_registry,
    get_recommend_pipeline,
    get_chat_completion_llm,
    get_supabase_creds,
    SupabaseCreds,
)
from app.deps.supabase_client import get_supabase_client, get_current_user_id
from app.repositories.taste_profile_store import fetch_user_taste_context


router = APIRouter(prefix="/discovery", tags=["discovery"])


def _item_view(c):
    p = c.payload
    return {
        "id": c.id,
        "media_id": p.get("media_id"),
        "title": p.get("title"),
        "genres": p.get("genres", []),
        "poster_url": p.get("poster_url"),
        "backdrop_url": p.get("backdrop_url"),
        "trailer_key": p.get("trailer_key"),
    }


@router.post("/for-you")
async def discover_for_you(
    req: DiscoverRequest,
    sb=Depends(get_supabase_client),
    user_id: str = Depends(get_current_user_id),
    registry=Depends(get_recipe_registry),
    pipeline=Depends(get_recommend_pipeline),
    chat_completion_llm=Depends(get_chat_completion_llm),
    creds: SupabaseCreds = Depends(get_supabase_creds),
):
    recipe = registry.get(kind="for_you_feed")
    user_context = await fetch_user_taste_context(sb, user_id, req.media_type.value)

    final_candidates, traces, llm_prompts = orchestrate(
        recipe=recipe,
        pipeline=pipeline,
        media_type=req.media_type.value,
        user_context=user_context,
    )

    return JSONResponse(
        {
            "query_id": req.query_id,
            "items": [_item_view(c) for c in final_candidates],
            "stream_url": f"/discovery/for-you/why?query_id={req.query_id}",
        }
    )


_TICKETS = {}


@router.post("/for-you/prepare")
async def prepare_stream_payload(
    req,
    sb=Depends(get_supabase_client),
    user_id: str = Depends(get_current_user_id),
    registry=Depends(get_recipe_registry),
    pipeline=Depends(get_recommend_pipeline),
):
    recipe = registry.get(kind="for_you_feed")
    user_context = await fetch_user_taste_context(sb, user_id, req.media_type.value)

    final_candidates, traces, llm_prompts = orchestrate(
        recipe=recipe,
        pipeline=pipeline,
        media_type=req.media_type.value,
        user_context=user_context,
    )
    _TICKETS[req.query_id] = {
        "candidates": final_candidates,
        "llm_prompts": llm_prompts,
    }
    return {"ok": True}

