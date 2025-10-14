from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from reelix_recommendation.orchestrator import orchestrate

# from reelix_logging.logger import log_final_results
from app.deps.deps import (
    get_recipe_registry,
    get_recommend_pipeline,
    get_chat_completion_llm,
)
from app.deps.supabase_optional import (
    get_optional_user_id,
    get_supabase_client_optional,
)
from app.repositories.taste_profile_store import fetch_user_taste_context
from app.schemas import InteractiveRequest

router = APIRouter(prefix="/recommend", tags=["recommend"])


@router.post("/interactive")
async def recommend_interactive(
    req: InteractiveRequest,
    sb=Depends(get_supabase_client_optional),
    user_id: str | None = Depends(get_optional_user_id),
    registry=Depends(get_recipe_registry),
    pipeline=Depends(get_recommend_pipeline),
    chat_llm=Depends(get_chat_completion_llm),
):
    recipe = registry.get(kind="interactive")
    user_context = None

    if user_id:
        user_context = await fetch_user_taste_context(sb, user_id, req.media_type.value)

    def gen():
        yield "[[MODE:recommendation]]\n"
        final_candidates, traces, llm_prompts = orchestrate(
            recipe=recipe,
            pipeline=pipeline,
            media_type=req.media_type.value,
            query_text=req.query_text,
            query_filter=req.query_filters,
            user_context=user_context,
        )

        messages = llm_prompts.calls[0].messages
        for chunk in chat_llm.stream(
            messages=messages,
            temperature=0.7,
        ):
            yield chunk

    return StreamingResponse(gen(), media_type="text/plain")


# @router.post("/log/final_recs")
# async def log_final_recommendations(
#     req: FinalRecsRequest, creds: SupabaseCreds = Depends(get_supabase_creds)
# ):
#     rows = [
#         {
#             "query_id": req.query_id,
#             "media_id": rec.media_id,
#             "is_final_rec": True,
#             "why_summary": rec.why,
#         }
#         for rec in req.final_recs
#     ]

#     try:
#         log_final_results(rows, creds)
#         return {"status": "ok"}
#     except Exception as e:
#         print(f"❌ Error logging final recs: {e}")
#         raise HTTPException(
#             status_code=500, detail="Failed to log final recommendations"
#         )
