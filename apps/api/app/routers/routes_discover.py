import json
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from reelix_recommendation.orchestrator import orchestrate

from app.deps.deps import (
    SupabaseCreds,
    get_chat_completion_llm,
    get_recipe_registry,
    get_recommend_pipeline,
    get_supabase_creds,
)
from app.deps.supabase_client import get_current_user_id, get_supabase_client
from app.deps.deps_ticket_store import get_ticket_store
from app.infrastructure.cache.ticket_store import Ticket
from app.repositories.taste_profile_store import fetch_user_taste_context
from app.schemas import DiscoverRequest

router = APIRouter(prefix="/discovery", tags=["discovery"])

IDLE_TTL_SEC = 15 * 60


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
    store=Depends(get_ticket_store),
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
    await store.put(
        req.query_id,  # ticket key
        Ticket(
            user_id=user_id,
            prompts=llm_prompts,
            meta={
                "recipe": "for_you_feed@v1",
                "items_brief": [
                    {"media_id": c.payload["media_id"], "title": c.payload["title"]}
                    for c in final_candidates[:12]
                ],
            },
        ),
        ttl_sec=IDLE_TTL_SEC,
    )

    return JSONResponse(
        {
            "query_id": req.query_id,
            "items": [_item_view(c) for c in final_candidates],
            "stream_url": f"/discovery/for-you/why?query_id={req.query_id}",
        }
    )


@router.get("/for-you/why")
async def stream_why(
    query_id: str,
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

    print(f"ticket: {ticket.prompts.calls[0].messages}")

    # def sse() -> Iterator[bytes]:
    #      yield b"event: started\ndata: {}\n\n"
    #     for chunk in chat_llm.stream_chat(
    #         [], system_prompt, user_prompt, temperature=0.7
    #     ):
    #         yield chunk

    # return StreamingResponse(gen(), media_type="text/plain")


@router.get("/for-you/why/old")
async def stream_why_old(
    query_id: str,
    user_id: str = Depends(get_current_user_id),
    chat_llm=Depends(get_chat_completion_llm),
):
    ticket = store.get(query_id)
    if not ticket:
        raise HTTPException(404, "Unknown or expired query_id")
    if ticket["user_id"] != user_id:
        raise HTTPException(403, "Forbidden")
    prompts = ticket["prompts"]

    def sse() -> Iterator[bytes]:
        yield b"event: started\ndata: {}\n\n"
        for delta in chat_llm.stream(prompts):
            yield f"event: why_delta\ndata: {json.dumps({'text': delta})}\n\n".encode(
                "utf-8"
            )
        # Alternative - per-title concurrency:
        # for media_id, p in prompts_by_media.items():
        #   for delta in chat_llm.stream(p):
        #       yield f\"event: why_delta\\ndata: {json.dumps({'media_id': media_id,'text': delta})}\\n\\n\".encode()

        yield b"event: done\ndata: {}\n\n"

    # delete ticket
    # _TICKETS.pop(query_id, None)
    return StreamingResponse(sse(), media_type="text/event-stream")
