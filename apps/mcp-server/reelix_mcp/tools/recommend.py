"""Tool 1: recommend_media — structured spec in, curated slate out.

The calling agent acts as the orchestrator: it translates the user's intent
into a structured spec (no planning LLM call here), and the pipeline runs the
same retrieval → curation path the web transport uses via
``run_rec_engine_direct`` — with identical Supabase telemetry.
"""

from __future__ import annotations

import time
import uuid

from opentelemetry import trace
from opentelemetry.trace import SpanKind

from reelix_agent.core.types import ExploreAgentInput, RecQuerySpec
from reelix_agent.explanation.explanation_prompts import build_why_prompt_envelope
from reelix_agent.orchestrator.active_spec import craft_active_spec
from reelix_agent.orchestrator.orchestrator_agent import run_rec_engine_direct
from reelix_core.types import MediaType
from reelix_logging.rec_logger import AgentDecisionLog, RequestTraceLog
from reelix_runtime.cache.ticket_store import Ticket
from reelix_runtime.session_memory import upsert_session_memory
from reelix_runtime.telemetry.links import otel_link_meta
from reelix_runtime.views import item_view

from reelix_mcp.runtime import AppContext

ENDPOINT = "mcp/explore"
PIPELINE_VERSION = "RecommendPipeline@v4"
BATCH_SIZE = 20

_tracer = trace.get_tracer(__name__)


def _mcp_item_view(c) -> dict:
    """Web item view minus image URLs, which a calling agent can't render."""
    item = item_view(c)
    item.pop("poster_url", None)
    item.pop("backdrop_url", None)
    return item


def build_spec(
    *,
    query_text: str,
    media_type: str,
    core_genres: list[str] | None,
    exclude_genres: list[str] | None,
    sub_genres: list[str] | None,
    core_tone: list[str] | None,
    key_themes: list[str] | None,
    providers: list[str] | None,
    year_range: list[int] | None,
) -> RecQuerySpec:
    """Lightweight validation of caller-agent args into a RecQuerySpec.

    Pydantic enforces types; unknown genre/provider strings are passed through
    deliberately (the Qdrant filter simply won't match them) until real caller
    behavior shows stricter validation is worthwhile.
    """
    text = (query_text or "").strip()
    if not text:
        raise ValueError("query_text must be a non-empty description of what to watch.")

    normalized_range: tuple[int, int] | None = None
    if year_range is not None:
        if len(year_range) != 2:
            raise ValueError("year_range must be [start_year, end_year].")
        start, end = int(year_range[0]), int(year_range[1])
        normalized_range = (start, end) if start <= end else (end, start)

    return RecQuerySpec(
        query_text=text,
        media_type=MediaType(media_type),
        core_genres=core_genres or [],
        exclude_genres=exclude_genres or [],
        sub_genres=sub_genres or [],
        core_tone=core_tone or [],
        key_themes=key_themes or [],
        providers=providers or [],
        year_range=normalized_range,
    )


async def run_recommend(
    ctx: AppContext,
    *,
    query_text: str,
    media_type: str = "movie",
    core_genres: list[str] | None = None,
    exclude_genres: list[str] | None = None,
    sub_genres: list[str] | None = None,
    core_tone: list[str] | None = None,
    key_themes: list[str] | None = None,
    providers: list[str] | None = None,
    year_range: list[int] | None = None,
    session_id: str | None = None,
) -> dict:
    query_id = str(uuid.uuid4())
    session_id = session_id or f"mcp-{uuid.uuid4()}"
    user_id = ctx.settings.anon_user_id
    t0 = time.perf_counter()

    with _tracer.start_as_current_span(
        "mcp.recommend_media", kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("reelix.query_id", query_id)
        span.set_attribute("reelix.session_id", session_id)
        span.set_attribute("reelix.transport", "mcp-stdio")
        try:
            spec = build_spec(
                query_text=query_text,
                media_type=media_type,
                core_genres=core_genres,
                exclude_genres=exclude_genres,
                sub_genres=sub_genres,
                core_tone=core_tone,
                key_themes=key_themes,
                providers=providers,
                year_range=year_range,
            )

            # 1) Session memory: a returning session_id makes this a refine turn
            #    (seen-media penalty against remembered ids).
            session_state = await ctx.stores.state_store.get_session(
                session_id=session_id, touch=True
            )
            turn_kind = "refine" if session_state else "new"

            agent_input = ExploreAgentInput(
                user_id=user_id,
                query_id=query_id,
                session_id=session_id,
                media_type=spec.media_type,
                query_text=spec.query_text,
                session_memory=session_state.to_orchestrator() if session_state else None,
                batch_size=BATCH_SIZE,
                device_info=None,
            )

            # 2) Record the caller agent's spec where orchestrator specs land,
            #    so agent_decisions covers MCP traffic too.
            ctx.spawn(
                ctx.logger.log_agent_decision(
                    AgentDecisionLog(
                        query_id=query_id,
                        session_id=session_id,
                        user_id=user_id,
                        mode="RECS",
                        decision_reasoning="mcp-direct-spec",
                        tool_called="recommendation_agent",
                        spec_json=spec.model_dump(mode="json"),
                        planning_latency_ms=0,
                        model="mcp-client",
                    )
                ),
                name="telemetry.agent_decision",
            )

            # 3) Pipeline → curator → tiers (same path as /explore/rerun)
            agent_result = await run_rec_engine_direct(
                agent_input=agent_input,
                spec=spec,
                agent_rec_runner=ctx.runtime.agent_rec_runner,
                llm_client=ctx.llm,
                tool_registry=ctx.runtime.tool_registry,
                tool_runner=ctx.runtime.tool_runner,
                logger=ctx.logger,
                turn_kind=turn_kind,
            )

            # 4) Persist session memory for follow-up refine turns
            await upsert_session_memory(
                state_store=ctx.stores.state_store,
                session_id=session_id,
                user_id=user_id,
                agent_result=agent_result,
            )

            # 5) Pipeline telemetry (same rows as the web transport)
            pipeline_traces = (
                agent_result.pipeline_traces[-1] if agent_result.pipeline_traces else {}
            )
            request_meta = {**(agent_result.meta or {}), "transport": "mcp-stdio"}
            ctx.spawn(
                ctx.logger.log_query_intake(
                    endpoint=ENDPOINT,
                    query_id=query_id,
                    user_id=user_id,
                    session_id=session_id,
                    media_type=spec.media_type.value,
                    query_text=spec.query_text,
                    ctx_log=agent_result.ctx_log,
                    pipeline_version=PIPELINE_VERSION,
                    batch_size=BATCH_SIZE,
                    device_info=None,
                    request_meta=request_meta,
                ),
                name="telemetry.query_intake",
            )
            ctx.spawn(
                ctx.logger.log_candidates(
                    endpoint=ENDPOINT,
                    query_id=query_id,
                    media_type=spec.media_type.value,
                    candidates=agent_result.candidates,
                    traces=pipeline_traces,
                    stage="prompt_context",
                ),
                name="telemetry.candidates",
            )

            # 6) Stash the WHY ticket so get_why_explanations can redeem it
            final_recs = agent_result.final_recs or []
            if final_recs and agent_result.query_spec:
                envelope = build_why_prompt_envelope(
                    candidates=final_recs,
                    query_spec=agent_result.query_spec,
                    batch_size=8,
                )
                await ctx.stores.ticket_store.put(
                    query_id,
                    Ticket(
                        user_id=user_id,
                        prompts=envelope.model_dump(mode="json"),
                        meta=otel_link_meta(),
                    ),
                    ttl_sec=ctx.settings.why_ticket_ttl_sec,
                )

            # 7) End-to-end request trace (2 LLM calls: parallel curator batches)
            tier_stats = agent_result.tier_stats or {}
            ctx.spawn(
                ctx.logger.log_trace(
                    RequestTraceLog(
                        query_id=query_id,
                        session_id=session_id,
                        user_id=user_id,
                        endpoint=ENDPOINT,
                        status="completed",
                        pipeline_ms=int(tier_stats["pipeline_ms"])
                        if "pipeline_ms" in tier_stats
                        else None,
                        curator_ms=int(tier_stats["curator_latency_ms"])
                        if "curator_latency_ms" in tier_stats
                        else None,
                        tier_ms=int(tier_stats["tier_latency_ms"])
                        if "tier_latency_ms" in tier_stats
                        else None,
                        total_ms=int((time.perf_counter() - t0) * 1000),
                        candidates_retrieved=len(agent_result.candidates)
                        if agent_result.candidates
                        else None,
                        candidates_served=len(final_recs) or None,
                        llm_calls=2,
                    )
                ),
                name="telemetry.trace",
            )

            active_spec = (
                craft_active_spec(agent_result.query_spec)
                if agent_result.query_spec
                else None
            )
            ttl_min = ctx.settings.why_ticket_ttl_sec // 60
            return {
                "query_id": query_id,
                "session_id": session_id,
                "active_filters": active_spec.model_dump(mode="json")
                if active_spec
                else None,
                "items": [_mcp_item_view(c) for c in final_recs],
                "why": {
                    "available": bool(final_recs),
                    "hint": (
                        f"Call get_why_explanations with this query_id within "
                        f"{ttl_min} minutes for per-title rationales."
                    ),
                },
            }
        except Exception as exc:
            span.record_exception(exc)
            ctx.spawn(
                ctx.logger.log_error(
                    query_id=query_id,
                    endpoint=ENDPOINT,
                    error_stage="unknown",
                    error=exc,
                    session_id=session_id,
                    user_id=user_id,
                    total_ms=int((time.perf_counter() - t0) * 1000),
                ),
                name="telemetry.error",
            )
            raise
