from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

from opentelemetry import trace

from reelix_agent.core.llm import call_llm_with_tools, LlmUsage
from reelix_agent.core.types import (
    AgentMode,
    ExploreAgentInput,
    RecAgentResult,
    LlmDecision,
    OrchestratorPlan,
    RecQuerySpec,
)
from reelix_agent.orchestrator.agent_rec_runner import AgentRecRunner
from reelix_agent.orchestrator.agent_state import AgentState
from reelix_agent.tools import ToolContext, ToolRegistry, ToolRunner
from reelix_core.llm_client import LlmClient

MEMORY_RE = re.compile(r"<MEMORY>\s*(.*?)\s*</MEMORY>", re.DOTALL)

_tracer = trace.get_tracer(__name__)
log = logging.getLogger(__name__)


async def plan_orchestrator_agent(
    *,
    agent_input: ExploreAgentInput,
    llm_client: LlmClient,
    tool_registry: ToolRegistry,
    max_steps: int | None = None,
    logger: Any | None = None,
) -> tuple[AgentState, OrchestratorPlan]:
    """
    Run the orchestrator LLM:
    - CHAT mode: return chat message
    - RECS mode: produce a plan with tool call

    Args:
        agent_input: User query input for this turn
        llm_client: LLM client for API calls
        tool_registry: Tool registry for tool discovery
        max_steps: Maximum planning steps (default: 3)
        logger: Telemetry logger for decision logging

    Returns:
        Tuple of (AgentState, OrchestratorPlan)
    """

    # Initialize agent state from input
    state = AgentState.from_agent_input(agent_input)
    state.turn_message = None
    state.turn_mode = None
    if max_steps is not None:
        state.max_steps = max_steps

    # Get tools from registry for LLM call
    tools = tool_registry.openai_tools()
    terminal_tools = tool_registry.terminal_tools()

    while not state.done and state.step_count < state.max_steps:
        state.step_count += 1
        with _tracer.start_as_current_span("orchestrator.plan") as plan_span:
            if state.query_id:
                plan_span.set_attribute("reelix.query_id", state.query_id)
            if state.session_id:
                plan_span.set_attribute("reelix.session_id", state.session_id)
            plan_start = time.perf_counter()
            decision, llm_usage = await call_llm_with_tools(state, llm_client=llm_client, tools=tools)
            planning_ms = int((time.perf_counter() - plan_start) * 1000)
            if not decision.is_tool_call:
                plan_span.set_attribute("reelix.orchestrator.mode", "CHAT")
            elif decision.tool_name in terminal_tools:
                plan_span.set_attribute("reelix.orchestrator.mode", "RECS")
        log.debug("Orchestrator decision: %s", decision)

        # == Case 1: Non-tool response: CHAT mode ==
        if not decision.is_tool_call:
            state.turn_mode = AgentMode.CHAT
            content_raw = (decision.content or "").strip()
            msg, memory_raw = _strip_memory_block(content_raw)

            mem: dict = {}
            if memory_raw:
                try:
                    parsed = json.loads(memory_raw)
                    if isinstance(parsed, dict):
                        mem.update(parsed)
                except Exception:
                    pass
            mem["turn_kind"] = "chat"  # Overwrite turn_kind to chat
            mem["last_user_message"] = state.user_text or ""
            mem["last_admin_message"] = msg

            state.turn_message = msg
            state.turn_memory = mem
            state.done = True
            _accumulate_orchestrator_usage(state, llm_usage)

            # Log CHAT mode decision
            if logger:
                asyncio.create_task(
                    _log_agent_decision(
                        logger=logger,
                        state=state,
                        mode="CHAT",
                        llm_usage=llm_usage,
                        planning_ms=planning_ms,
                        tool_called=None,
                        spec_json=None,
                        opening_summary=None,
                    )
                )

            return state, OrchestratorPlan(
                mode=state.turn_mode,
                decision=None,
                opening_summary=None,
                message=msg,
            )

        # == Case 2: Tool call: if terminal, return plan; else execute and continue ==
        tool = decision.tool_name
        if tool in terminal_tools:
            state.turn_mode = AgentMode.RECS
            tool_args = decision.tool_args or {}
            opening = tool_args.get("opening_summary")
            raw_spec = tool_args.get("rec_query_spec") or {}
            state.query_spec = RecQuerySpec(**raw_spec)
            _accumulate_orchestrator_usage(state, llm_usage)

            # Log RECS mode decision
            if logger:
                asyncio.create_task(
                    _log_agent_decision(
                        logger=logger,
                        state=state,
                        mode="RECS",
                        llm_usage=llm_usage,
                        planning_ms=planning_ms,
                        tool_called=tool,
                        spec_json=raw_spec,
                        opening_summary=opening if isinstance(opening, str) else None,
                    )
                )

            return state, OrchestratorPlan(
                mode=state.turn_mode,
                decision=decision,
                opening_summary=opening if isinstance(opening, str) else None,
                message=None,
            )

        # == Reserve for non-terminal tools ==
        raise RuntimeError(
            f"Unknown non-terminal tool '{tool}' produced by orchestrator. "
        )

    # Fallback: if loop exits unexpectedly, return a safe chat
    msg = "I'm not sure how to proceed. Please try again."
    state.turn_mode = AgentMode.CHAT
    state.turn_message = msg
    state.done = True
    return state, OrchestratorPlan(
        mode=state.turn_mode,
        decision=None,
        opening_summary=None,
        message=msg,
    )


async def execute_orchestrator_plan(
    *,
    state: AgentState,
    plan: OrchestratorPlan,
    agent_rec_runner: AgentRecRunner,
    llm_client: LlmClient,
    tool_registry: ToolRegistry,
    tool_runner: ToolRunner,
    logger: Any | None = None,
) -> RecAgentResult:
    """
    Execute a previously produced OrchestratorPlan.
    - RECS: executes the recommendation_agent tool call via ToolRunner.
    - CHAT: returns the chat message directly.

    Args:
        state: mutated AgentState from plan_orchestrator_agent
        plan: OrchestratorPlan to execute
        agent_rec_runner: Recommendation pipeline runner
        llm_client: LLM client for curator calls
        tool_registry: Tool registry for tool discovery (required)
        tool_runner: Tool runner for tool execution (required)
        logger: Telemetry logger for curator logging

    Returns:
        RecAgentResult with recommendations or chat message
    """

    # == CHAT mode: ==
    if plan.mode == "CHAT":
        return _result_from_state(state)

    # Defensive
    if plan.decision is None:
        state.turn_mode = AgentMode.CHAT
        state.turn_message = plan.message or "I'm not sure how to proceed. Please try again."
        state.done = True
        return _result_from_state(state)

    # == RECS mode: Execute the tool call via ToolRunner ==
    ctx = ToolContext(
        state=state,
        agent_rec_runner=agent_rec_runner,
        llm_client=llm_client,
        extra={"logger": logger} if logger else {},
    )

    result = await tool_runner.run(decision=plan.decision, ctx=ctx)

    # Log any errors (tool already logs trace to state.agent_trace)
    if result.is_error:
        log.error("[orchestrator] tool error: %s", result.error_message)

    state.done = True
    return _result_from_state(state)


async def run_rec_engine_direct(
    agent_input: ExploreAgentInput,
    spec: RecQuerySpec,
    agent_rec_runner: AgentRecRunner,
    llm_client: LlmClient,
    tool_registry: ToolRegistry,
    tool_runner: ToolRunner,
    logger: Any | None = None,
    turn_kind: str = "refine",
) -> RecAgentResult:
    """
    Run the recommendation engine directly without LLM planning.
    Used for chip-based filter reruns and direct-spec transports (MCP).

    Args:
        agent_input: User input for context
        spec: Pre-built RecQuerySpec
        agent_rec_runner: Recommendation pipeline runner
        user_context_service: User context service (unused)
        llm_client: LLM client for curator
        tool_registry: Tool registry (required, unused in this function but kept for consistency)
        tool_runner: Tool runner for executing recommendation_agent tool (required)
        logger: Telemetry logger for curator logging
        turn_kind: "refine" applies the seen-media penalty against session
            memory; "new" treats the query as a fresh turn

    Returns:
        InteractiveAgentResult with recommendations
    """

    state = AgentState.from_agent_input(agent_input)

    tool_args = {
        "rec_query_spec": spec.model_dump(mode="json"),
        "memory_delta": {"turn_kind": turn_kind, "recent_feedback": None},
    }
    decision = LlmDecision(
        is_tool_call=True,
        tool_name="recommendation_agent",
        tool_args=tool_args,
        tool_call_id="chip_rerun",
    )

    ctx = ToolContext(
        state=state,
        agent_rec_runner=agent_rec_runner,
        llm_client=llm_client,
        extra={"logger": logger} if logger else {},
    )

    await tool_runner.run(decision=decision, ctx=ctx)

    state.done = True

    return RecAgentResult(
        mode=state.turn_mode or AgentMode.RECS,
        query_spec=state.query_spec,
        candidates=state.candidates,
        final_recs=state.final_recs,
        summary=state.curator_opening or "",
        turn_memory=state.turn_memory,
        ctx_log=state.ctx_log,
        pipeline_traces=state.pipeline_traces,
        agent_trace=state.agent_trace,
        meta=state.meta,
        tier_stats=state.tier_stats,
    )


def _accumulate_orchestrator_usage(state: AgentState, llm_usage: LlmUsage) -> None:
    """Add one orchestrator LLM call's usage to the running per-request totals.

    Accumulates rather than overwrites: the planning loop may run several steps,
    and the request trace needs the sum of them all.
    """
    state.meta["orchestrator_llm_calls"] = state.meta.get("orchestrator_llm_calls", 0) + 1
    state.meta["orchestrator_input_tokens"] = (
        state.meta.get("orchestrator_input_tokens") or 0
    ) + (llm_usage.input_tokens or 0)
    state.meta["orchestrator_output_tokens"] = (
        state.meta.get("orchestrator_output_tokens") or 0
    ) + (llm_usage.output_tokens or 0)


def _strip_memory_block(text: str) -> tuple[str, str | None]:
    """
    Returns (cleaned_message, memory_raw_json_or_text)
    If no block exists, memory is None.
    """
    text = text or ""
    m = MEMORY_RE.search(text)
    memory_raw = m.group(1).strip() if m else None

    # remove the whole block if present
    cleaned = MEMORY_RE.sub("", text).strip()

    return cleaned, memory_raw


def _result_from_state(state: AgentState) -> RecAgentResult:
    return RecAgentResult(
        mode=state.turn_mode or AgentMode.RECS,
        # Domain outputs
        query_spec=state.query_spec,
        candidates=state.candidates,
        final_recs=state.final_recs,
        # Memory + traces
        turn_memory=state.turn_memory,
        ctx_log=state.ctx_log,
        pipeline_traces=state.pipeline_traces,
        agent_trace=state.agent_trace,
        meta=state.meta,
        tier_stats=state.tier_stats,
    )


async def _log_agent_decision(
    *,
    logger: Any,
    state: AgentState,
    mode: str,
    llm_usage: LlmUsage,
    planning_ms: int,
    tool_called: str | None,
    spec_json: dict | None,
    opening_summary: str | None,
) -> None:
    """Log orchestrator agent decision to Supabase.

    Args:
        logger: TelemetryLogger instance
        state: AgentState with query/session info
        mode: "CHAT" or "RECS"
        llm_usage: Token usage from LLM call
        planning_ms: Planning latency in milliseconds
        tool_called: Tool name if RECS mode
        spec_json: RecQuerySpec dict if RECS mode
        opening_summary: Opening summary if RECS mode
    """
    # Lazy import to avoid circular dependency
    from reelix_logging.rec_logger import AgentDecisionLog

    try:
        await logger.log_agent_decision(
            AgentDecisionLog(
                query_id=state.query_id,
                session_id=state.session_id,
                user_id=state.user_id,
                turn_number=state.step_count,
                mode=mode,
                decision_reasoning=None, # Not requried for orchestrator
                tool_called=tool_called,
                spec_json=spec_json,
                opening_summary=opening_summary,
                # The orchestrator's *input* for this turn. Logged so a decision
                # can be replayed: on a refine turn the spec depends on the
                # session-memory system message, not just query_text.
                session_memory=state.session_memory,
                planning_latency_ms=planning_ms,
                input_tokens=llm_usage.input_tokens,
                output_tokens=llm_usage.output_tokens,
                model=llm_usage.model,
            )
        )
    except Exception as e:
        log.warning("[agent_logging] Failed to log decision: %s", e)