from fastapi import APIRouter

from api.app.schemas import DiscoverRequest
from fastapi.responses import JSONResponse


router = APIRouter(prefix="/discovery", tags=["discovery"])


@router.post("/for-you")
def discover(req: DiscoverRequest):
    final, traces, profile = orchestrate_recs(
        media_type=req.media_type,
        query_text=None,
        user_context=req.user_context,
        user_id=req.user_id,
    )
    out = to_json(final, traces)  # no LLM by default
    if req.include_llm_why:
        out["why_md"] = llm_curate(profile, final)  # non-stream, one-shot
    return JSONResponse(out)
