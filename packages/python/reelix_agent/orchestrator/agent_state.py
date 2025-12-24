from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from pydantic import Field

from anyio import to_thread
from reelix_core.types import UserTasteContext
from reelix_ranking.types import Candidate, ScoreTrace
from reelix_agent.core.types import (
    AgentBaseModel,
    InteractiveAgentInput,
    RecQuerySpec,
    LlmDecision,
    AgentMode,
)
from reelix_llm.client import LlmClient
from reelix_agent.orchestrator.orchestrator_prompts import (
    ORCHESTRATOR_SYSTEM_PROMPT,
    build_orchestrator_user_prompt,
    build_session_memory_message,
)
from reelix_agent.curator.curator_agent import run_curator_agent
from reelix_agent.curator.curator_tiers import apply_curator_tiers

if TYPE_CHECKING:
    from reelix_agent.orchestrator.agent_rec_runner import AgentRecRunner
else:
    AgentRecRunner = Any  # type: ignore


class AgentState(AgentBaseModel):
    # IDs / metadata
    user_id: str
    query_id: str
    session_id: str | None = None
    media_type: str | None = None  # or your MediaType enum
    device_info: Any | None = None

    # LLM conversational state
    messages: list[dict[str, Any]] = Field(default_factory=list)
    session_memory: dict[str, Any] | None = None
    seen_media_ids: list[int] = Field(default_factory=list)
    prior_spec: RecQuerySpec | None = None
    slot_map: dict[str, Any] | None = None

    # Per-turn routing + output
    turn_mode: AgentMode | None = None
    turn_kind: str | None = None
    turn_message: str | None = None
    turn_memory: dict[str, Any] | None = None

    # Domain state
    user_context: UserTasteContext
    query_spec: RecQuerySpec | None = None
    candidates: list[Candidate] = Field(default_factory=list)
    curator_opening: str | None = None
    curator_eval: list = Field(default_factory=list)
    final_recs: list[Candidate] = Field(default_factory=list)
    final_summary: str | None = None

    # Control
    step_count: int = 0
    max_steps: int = 3  # Maximun turns. Reserved for multipple tool calls per turn
    done: bool = False

    # Telemetry / traces
    ctx_log: dict[str, Any] | None = None  # whatever you log today
    pipeline_traces: list[dict[int, ScoreTrace]] = Field(
        default_factory=list
    )  # dense/sparse/meta traces, etc.
    agent_trace: list[dict[str, Any]] = Field(
        default_factory=list
    )  # sequence of tool calls
    meta: dict[str, Any] = Field(default_factory=dict)  # recipe, versions, etc.

    @classmethod
    def from_agent_input(
        cls, agent_input: InteractiveAgentInput, user_context: UserTasteContext
    ) -> "AgentState":
        """
        Bootstrap a fresh AgentState from the HTTP-level input.

        Called at the start of an interactive agent run
        (new query_id / session), before any tools are invoked.
        """
        # Build the initial user message content the LLM sees
        user_msg_content = build_orchestrator_user_prompt(agent_input)
        mem_msg, prior_spec, slot_map = build_session_memory_message(agent_input.session_memory)
        
        print ("memory message: ", mem_msg)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": ORCHESTRATOR_SYSTEM_PROMPT},
            *([{"role": "system", "content": mem_msg}] if mem_msg else []),
            {"role": "user", "content": user_msg_content},
        ]
    
        # Pull seen_media_ids from session memory for pipeline exclusion (intent-scoped)
        seen_ids: list[int] = []
        if isinstance(agent_input.session_memory, dict):
            raw = agent_input.session_memory.get("seen_media_ids") or []
            if isinstance(raw, list):
                seen_ids = [int(x) for x in raw if isinstance(x, (int, str)) and str(x).isdigit()]

        return cls(
            user_id=agent_input.user_id,
            query_id=agent_input.query_id,
            session_id=agent_input.session_id,
            media_type=str(agent_input.media_type) if agent_input.media_type else None,
            device_info=agent_input.device_info,
            messages=messages,
            user_context=user_context,
            session_memory=agent_input.session_memory,
            seen_media_ids=seen_ids,          
        )

    async def execute_tool_call(
        self,
        *,
        decision: LlmDecision,
        agent_rec_runner: AgentRecRunner,
        llm_client: LlmClient,
    ) -> None:
        """
        Execute a tool requested by the LLM.

        - Mutates AgentState (query_spec, candidates, etc.).
        - Appends a tool result message into self.messages so the LLM sees the outcome on the next step.
        - Records an entry in agent_trace.

        Tools supported:
          - call_rec_engine(rec_query_spec)
        """
        tool_name = decision.tool_name
        tool_call_id = decision.tool_call_id
        tool_args = decision.tool_args or {}

        if tool_name == "recommendation_agent":
            self.turn_mode = AgentMode.RECS
            await self._exec_recommendations_pipeline(
                tool_call_id,
                tool_args,
                agent_rec_runner=agent_rec_runner,
                llm_client=llm_client,
            )
            return

        # Unknown tool: record and return a small error payload
        payload = {"error": f"Unknown tool '{tool_name}'", "args": tool_args}
        self.agent_trace.append(
            {
                "step": self.step_count,
                "tool": tool_name,
                "args": tool_args,
                "result": payload,
            }
        )
        self.messages.append(
            {
                "role": "tool",
                "name": tool_name or "unknown",
                "tool_call_id": decision.tool_call_id,
                "content": json.dumps(payload),
            }
        )

    async def _exec_recommendations_pipeline(
        self,
        tool_call_id,
        tool_args: dict[str, Any],
        agent_rec_runner: AgentRecRunner,
        llm_client: LlmClient,
    ) -> None:
        # 1) Parse tool_args for turn_memory and RecQuerySpec
        mem = tool_args.get("memory_delta")
        if isinstance(mem, dict):
            self.turn_memory = mem
            self.turn_kind = mem.get("turn_kind")

        raw_spec = tool_args.get("rec_query_spec") or {}
        spec = RecQuerySpec(**raw_spec)
        self.query_spec = spec

        # 2) Make sure user_context exists
        if self.user_context is None and self.user_id is not None:
            pass

        # 3) Call rec pipeline
        candidates: list[Candidate] = []
        traces: dict[int, ScoreTrace]
        ctx_log: dict[str, Any] | None = None

        def _run_agent_sync():
            return agent_rec_runner.run_for_agent(
                user_context=self.user_context,
                spec=spec,
                seen_media_ids=self.seen_media_ids,
                turn_kind= self.turn_kind,
            )

        candidates, traces, ctx_log = await to_thread.run_sync(_run_agent_sync)

        self.candidates = candidates
        if traces:
            self.pipeline_traces.append(traces)
        if ctx_log:
            self.ctx_log = ctx_log

        # 4) Call the curator agent llm
        curator_output = await run_curator_agent(
            query_text=spec.query_text,
            spec=self.query_spec,
            candidates=candidates,
            llm_client=llm_client,
            user_signals=None,
        )
        curator_output = json.loads(curator_output)

        self.curator_opening = curator_output.get("opening", "")
        self.curator_eval = curator_output.get("evaluation_results", [])

        self.final_recs, stats = apply_curator_tiers(
            evaluation_results=self.curator_eval,
            candidates=self.candidates,
            limit=spec.num_recs or 8,
        )

        # 5) Record trace + append tool result message for multi-turn requests
        self.agent_trace.append(
            {
                "step": self.step_count,
                "tool": "call_curator_agent",
                "args": tool_args,
                "result": {"count": len(self.curator_eval)},
            }
        )
        self.messages.append(
            {
                "role": "tool",
                "name": "call_curator_agent",
                "tool_call_id": tool_call_id,
                "content": curator_output,
            }
        )
