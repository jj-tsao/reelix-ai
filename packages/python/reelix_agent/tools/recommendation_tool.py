from __future__ import annotations
import json
import time
from typing import Any

from pydantic import BaseModel, Field

from reelix_agent.core.types import RecQuerySpec, AgentMode
from reelix_agent.curator.curator_agent import run_curator_agent
from reelix_agent.curator.curator_tiers import apply_curator_tiers
from .types import ToolContext, ToolResult

class RecommendationArgs(BaseModel):
    rec_query_spec: RecQuerySpec
    opening_summary: str = Field(..., description="2 sentences")
    memory_delta: dict[str, Any] | None = None

async def recommendation_handler(ctx: ToolContext, args: RecommendationArgs) -> ToolResult:
    state = ctx.state
    spec = args.rec_query_spec

    # Apply “turn memory” into state (so session_memory builder can write it)
    turn_mem = args.memory_delta or {}
    state.turn_memory = turn_mem
    state.turn_kind = turn_mem.get("turn_kind")
    state.turn_mode = AgentMode.RECS
    state.query_spec = spec

    # 1) Rec pipeline (sync runner wrapped)
    def _run_agent_sync():
        return ctx.agent_rec_runner.run_for_agent(
            user_context=state.user_context,
            spec=spec,
            seen_media_ids=state.seen_media_ids,
            turn_kind=state.turn_kind,
        )

    t0 = time.perf_counter()
    candidates, traces, ctx_log = await ctx.state.to_thread.run_sync(_run_agent_sync)  # or anyio.to_thread
    pipeline_ms = (time.perf_counter() - t0) * 1000

    # 2) Curator
    t1 = time.perf_counter()
    raw = await run_curator_agent(
        query_text=spec.query_text,
        spec=spec,
        candidates=candidates,
        llm_client=ctx.llm_client,
        user_signals=None,
    )
    curator_ms = (time.perf_counter() - t1) * 1000

    try:
        curator_payload = json.loads(raw)
    except Exception:
        curator_payload = {"evaluation_results": []}

    final_recs, stats = apply_curator_tiers(
        evaluation_results=curator_payload.get("evaluation_results", []),
        candidates=candidates,
        limit=spec.num_recs or 8,
    )

    # Patch state (single place)
    patch = {
        "candidates": candidates,
        "final_recs": final_recs,
        "ctx_log": ctx_log,
        # keep traces small; you can stash full traces elsewhere
        "curator_opening": args.opening_summary,
    }

    # Return minimal tool payload (don’t dump 20 full items back into the LLM unless needed)
    payload = {
        "ok": True,
        "counts": {"candidates": len(candidates), "final_recs": len(final_recs)},
        "timing_ms": {"pipeline": pipeline_ms, "curator": curator_ms},
    }

    return ToolResult(payload=payload, state_patch=patch, terminal=True)
