import json
import time
import asyncio
from typing import Iterator
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from reelix_core.types import PromptsEnvelope
from reelix_recommendation.orchestrator import orchestrate

from app.deps.deps import (
    get_chat_completion_llm,
    get_recipe_registry,
    get_recommend_pipeline,
    get_logger,
)
from app.deps.supabase_client import (
    get_current_user_id,
    get_user_context_service,
)
from app.deps.deps_ticket_store import get_ticket_store
from app.infrastructure.cache.ticket_store import Ticket
from app.schemas import DiscoverRequest, FinalRecsRequest

router = APIRouter(prefix="/discovery", tags=["discovery"])

ENDPOINT = "discovery/for-you"
IDLE_TTL_SEC = 15 * 60
HEARTBEAT_SEC = 15


def _item_view(c):
    p = c.payload or {}
    return {
        "id": c.id,
        "media_id": p.get("media_id"),
        "title": p.get("title"),
        "release_year": p.get("release_year"),
        "genres": p.get("genres", []),
        "poster_url": p.get("poster_url"),
        "backdrop_url": p.get("backdrop_url"),
        "trailer_key": p.get("trailer_key"),
    }


@router.post("/for-you")
async def discover_for_you(
    req: DiscoverRequest,
    batch_size: int = 8,
    user_id: str = Depends(get_current_user_id),
    registry=Depends(get_recipe_registry),
    user_context=Depends(get_user_context_service),
    pipeline=Depends(get_recommend_pipeline),
    store=Depends(get_ticket_store),
    logger=Depends(get_logger),
):
    recipe = registry.get(kind="for_you_feed")
    user_context = await user_context.fetch_user_taste_context(user_id, req.media_type)

    final_candidates, traces, ctx_log, llm_prompts = orchestrate(
        recipe=recipe,
        pipeline=pipeline,
        media_type=req.media_type.value,
        batch_size=batch_size,
        user_context=user_context,
    )
    print (llm_prompts)
    ticket = Ticket(
        user_id=user_id,
        prompts=llm_prompts,
        meta={
            "recipe": "for_you_feed@v1",
            "items_brief": [
                {
                    "media_id": (c.payload or {}).get("media_id"),
                    "title": (c.payload or {}).get("title"),
                }
                for c in final_candidates[:batch_size]
            ],
        },
    )

    await store.put(
        req.query_id,  # ticket key
        ticket,
        ttl_sec=IDLE_TTL_SEC,
    )

    asyncio.create_task(
        logger.log_query_intake(
            endpoint=ENDPOINT,
            query_id=req.query_id,
            user_id=user_id,
            session_id=req.session_id,
            media_type=req.media_type,
            ctx_log=ctx_log,
            pipeline_version="RecommendPipeline@v2",
            batch_size=batch_size,
            device_info=req.device_info,
            request_meta=ticket.meta,
        )
    )

    asyncio.create_task(
        logger.log_candidates(
            endpoint=ENDPOINT,
            query_id=req.query_id,
            media_type=req.media_type,
            candidates=final_candidates[:batch_size],
            traces=traces,
            stage="final",
        )
    )

    return JSONResponse(
        {
            "query_id": req.query_id,
            "items": [_item_view(c) for c in final_candidates[:batch_size]],
            "stream_url": f"/discovery/for-you/why?query_id={req.query_id}",
        }
    )


@router.get("/for-you/why")
async def stream_why(
    query_id: str,
    batch: int = 1,
    user_id: str = Depends(get_current_user_id),
    store=Depends(get_ticket_store),
    chat_llm=Depends(get_chat_completion_llm),
):
    ticket = await store.get(query_id)
    if not ticket:
        raise HTTPException(404, "Unknown or expired query")
    if ticket.user_id != user_id:
        raise HTTPException(403, "Forbidden")
    await store.touch(query_id, IDLE_TTL_SEC)

    try:
        env = PromptsEnvelope.model_validate(ticket.prompts)
    except Exception as e:
        raise HTTPException(500, f"Invalid prompt envelope: {e}")

    picked = _pick_call(env, batch)
    messages = picked["messages"]
    batch_id = picked["batch_id"]

    model = env.model
    params = dict(env.params or {})

    def gen() -> Iterator[bytes]:
        last_hb = time.time()
        yield _sse(
            "started",
            {
                "query_id": query_id,
                "batch_id": batch_id,
            },
        )

        # Global JSONL: buffer by newline and emit per-item deltas
        buffer = ""
        try:
            stream_iter = chat_llm.stream(messages, model=model, **params)
            for delta in stream_iter:
                # Heartbeat
                now = time.time()
                if now - last_hb >= HEARTBEAT_SEC:
                    yield b":\n\n"  # comment frame
                    last_hb = now

                buffer += delta
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        media_id = obj.get("media_id")
                        imdb_rating = obj.get("imdb_rating")
                        rotten_tomatoes_rating = obj.get("rotten_tomatoes_rating")
                        why_md = obj.get("why_md")
                        if not media_id or not isinstance(why_md, str):
                            continue
                        yield _sse(
                            "why_delta",
                            {
                                "media_id": media_id,
                                "imdb_rating": imdb_rating,
                                "rotten_tomatoes_rating": rotten_tomatoes_rating,
                                "why_you_might_enjoy_it": why_md,
                            },
                        )
                    except json.JSONDecodeError:
                        # Incomplete JSON line; keep buffering
                        buffer = line + "\n" + buffer
                        break
            # Flush a trailing JSON line if complete
            tail = buffer.strip()
            if tail:
                try:
                    obj = json.loads(tail)
                    media_id = obj.get("media_id")
                    imdb_rating = obj.get("imdb_rating")
                    rotten_tomatoes_rating = obj.get("rotten_tomatoes_rating")
                    why_md = obj.get("why_md")
                    if media_id and isinstance(why_md, str):
                        yield _sse(
                            "why_delta",
                            {
                                "media_id": media_id,
                                "imdb_rating": imdb_rating,
                                "rotten_tomatoes_rating": rotten_tomatoes_rating,
                                "why_you_might_enjoy_it": why_md,
                            },
                        )
                except Exception:
                    pass

            yield _sse("done", {"ok": True})
        except Exception as e:
            yield _sse("error", {"message": str(e)})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
        },
    )

    # === TEST - Simple Streaming ===
    # return StreamingResponse(
    #     gen(),
    #     media_type="text/event-stream",
    #     headers={
    #         "Cache-Control": "no-cache, no-transform",
    #         "Connection": "keep-alive",
    #     },
    # )


@router.post("/log/final_recs")
async def log_final_recommendations(
    req: FinalRecsRequest,
    logger=Depends(get_logger),
):
    asyncio.create_task(
        logger.log_why(
            endpoint=ENDPOINT,
            query_id=req.query_id,
            final_recs=req.final_recs,
        )
    )


def _pick_call(env: PromptsEnvelope, batch: int | None) -> dict:
    if not env.calls:
        raise HTTPException(500, "Envelope has no calls")

    call = None
    if batch is not None:
        for c in env.calls:
            if getattr(c, "call_id", None) == batch:
                call = c
                break
        if call is None:
            raise HTTPException(404, f"Batch {batch} not found")
    else:
        call = env.calls[0]

    return {
        "messages": call.messages,
        "items_brief": getattr(call, "items_brief", []),
        "media_id": getattr(call, "media_id", None),
        "batch_id": getattr(call, "call_id", None),
    }


def _sse(event: str, data: dict | str) -> bytes:
    if isinstance(data, dict):
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    else:
        payload = data
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")
