from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from app.schemas import FinalRecsRequest, InteractiveRequest
from services.usage_logger import log_final_results
from app.deps import get_interactive_stream_fn, SupabaseCreds, get_supabase_creds


router = APIRouter(prefix="/recommend", tags=["recommend"])


@router.post("/interactive")
async def recommend_interactive(
    req: InteractiveRequest,
    stream_fn=Depends(get_interactive_stream_fn),
    creds: SupabaseCreds = Depends(get_supabase_creds),
):
    def response_stream():
        generator = stream_fn(
            query_text=req.query_text,
            history=req.history,
            media_type=req.media_type,
            genres=req.query_filters.genres,
            providers=req.query_filters.providers,
            year_range=tuple(req.query_filters.year_range),
            session_id=req.session_id,
            query_id=req.query_id,
            device_info=req.device_info,
            logging_creds=creds,
            logging=False,
        )
        for chunk in generator:
            yield chunk

    return StreamingResponse(response_stream(), media_type="text/plain")


@router.post("/log/final_recs")
async def log_final_recommendations(
    req: FinalRecsRequest, creds: SupabaseCreds = Depends(get_supabase_creds)
):
    rows = [
        {
            "query_id": req.query_id,
            "media_id": rec.media_id,
            "is_final_rec": True,
            "why_summary": rec.why,
        }
        for rec in req.final_recs
    ]

    try:
        log_final_results(rows, creds)
        return {"status": "ok"}
    except Exception as e:
        print(f"❌ Error logging final recs: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to log final recommendations"
        )
