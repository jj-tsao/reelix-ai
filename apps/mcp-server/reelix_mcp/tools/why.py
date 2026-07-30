"""Tool 2: get_why_explanations — redeem a query_id for all rationales.

Reuses the idempotent Redis ticket written by recommend_media: the ticket
holds fully-rendered LLM prompts, is touched (never deleted) on read, and can
be redeemed repeatedly until its TTL lapses. Unlike the web SSE endpoint this
aggregates every envelope call into one blocking payload.
"""

from __future__ import annotations

import asyncio

from opentelemetry import trace
from opentelemetry.trace import SpanKind

from reelix_agent.core.types import LLMCall, PromptsEnvelope
from reelix_agent.explanation.explanation_agent import stream_why_events
from reelix_runtime.telemetry.links import link_from_ticket_meta

from reelix_mcp.runtime import AppContext

# No consumer to keep alive over MCP; effectively disables heartbeat events.
HEARTBEAT_SEC = 120.0

_tracer = trace.get_tracer(__name__)


async def run_why(ctx: AppContext, *, query_id: str) -> dict:
    ticket = await ctx.stores.ticket_store.get(query_id)
    if not ticket:
        raise ValueError(
            "Unknown or expired query_id — call recommend_media again for a fresh one."
        )
    if ticket.user_id != ctx.settings.anon_user_id:
        raise ValueError("query_id was not created by this server.")
    await ctx.stores.ticket_store.touch(query_id, ctx.settings.why_ticket_ttl_sec)

    try:
        envelope = PromptsEnvelope.model_validate(ticket.prompts)
    except Exception as exc:
        raise ValueError(f"Invalid prompt envelope for query_id: {exc}") from exc
    if not envelope.calls:
        raise ValueError("No explanation prompts stored for this query_id.")

    # Join this trace back to the originating recommend_media trace.
    parent_link = link_from_ticket_meta(ticket.meta)
    with _tracer.start_as_current_span(
        "mcp.get_why_explanations",
        kind=SpanKind.SERVER,
        links=[parent_link] if parent_link else None,
    ) as span:
        span.set_attribute("reelix.query_id", query_id)
        span.set_attribute("reelix.transport", "mcp-stdio")

        titles: dict[str, str | None] = {}
        for call in envelope.calls:
            for brief in getattr(call, "items_brief", None) or []:
                titles[str(brief.get("media_id"))] = brief.get("title")

        params = dict(envelope.params or {})

        async def collect(call: LLMCall) -> list:
            items = []
            async for event in stream_why_events(
                chat_llm=ctx.llm,
                messages=call.messages,
                model=envelope.model,
                params=params,
                heartbeat_sec=HEARTBEAT_SEC,
            ):
                if event.type == "item" and event.item is not None:
                    items.append(event.item)
            return items

        batches = await asyncio.gather(*(collect(call) for call in envelope.calls))
        explanations = [
            {
                "media_id": item.media_id,
                "title": titles.get(str(item.media_id)),
                "why": item.why,
            }
            for batch in batches
            for item in batch
        ]
        return {
            "query_id": query_id,
            "explanations": explanations,
            "count": len(explanations),
        }
