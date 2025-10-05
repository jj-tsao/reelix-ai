from fastapi import APIRouter, Depends
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

    return None

    # out = to_json(final, traces)  # no LLM by default
    # if req.include_llm_why:
    #     out["why_md"] = llm_curate(profile, final)  # non-stream, one-shot
    # return JSONResponse(out)
