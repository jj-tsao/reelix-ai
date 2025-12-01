from __future__ import annotations

import json
from enum import Enum
from typing import TYPE_CHECKING, Any

from anyio import to_thread
from pydantic import BaseModel, ConfigDict
from reelix_core.types import MediaType, QueryFilter, UserTasteContext
from reelix_ranking.types import Candidate, ScoreTrace
from reelix_user_context.user_context_service import UserContextService
from reelix_agent.interactive.prompts import REC_AGENT_SYSTEM_PROMPT
from reelix_agent.interactive.tools import call_rec_engine

if TYPE_CHECKING:
    from reelix_agent.interactive.agent_rec_pipeline import AgentRecRunner
else:
    AgentRecRunner = Any  # type: ignore


class AgentBaseModel(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)


class InteractiveAgentInput(AgentBaseModel):
    user_id: str
    query_id: str
    session_id: str | None
    media_type: MediaType
    query_text: str
    query_filters: QueryFilter
    user_context_service: UserContextService
    batch_size: int = 20
    device_info: Any | None = None


class InteractiveAgentResult(AgentBaseModel):
    final_recs: list[FinalRec]
    summary: str
    ctx_log: dict | None = None
    pipeline_traces: list[dict] = []
    agent_trace: list[dict] = []
    meta: dict = {}


class AgentMode(str, Enum):
    RECS = "recs"  # default
    # EXPLAIN = "explain"    # "why this / why not that"
    PREFS = "preferences"  # set preferences


class RecQuerySpec(BaseModel):
    mode: AgentMode = AgentMode.RECS
    query_text: str  # raw NL query / vibes
    media_type: MediaType = MediaType.MOVIE
    seed_titles: list[str] = []
    include_genres: list[str] = []
    exclude_genres: list[str] = []
    include_keywords: list[str] = []
    exclude_keywords: list[str] = []
    providers: list[str] = []  # e.g. ["netflix", "hulu"]
    max_runtime_minutes: int | None = None
    min_rating: float | None = None
    tone: str | None = None  # "not too dark", "cozy", etc
    limit: int = 20


class LlmDecision(AgentBaseModel):
    """
    Normalized result of a single LLM call with tools.
    """

    is_tool_call: bool
    content: str | None = None
    tool_name: str | None = None  # function name if is_tool_call=True
    tool_args: dict[str, Any] = {}  # parsed JSON args if is_tool_call=True
    tool_call_id: str | None = None  # id for the tool call (OpenAI API)


class FinalRec(AgentBaseModel):
    media_id: int
    title: str
    media_type: str
    overview: str
    providers: list[str]
    score: float
    why: str | None = None


class AgentState(AgentBaseModel):
    # IDs / metadata
    user_id: str
    query_id: str
    session_id: str | None = None
    media_type: str | None = None  # or your MediaType enum
    device_info: Any | None = None

    # LLM conversational state
    messages: list[dict[str, Any]] = []

    # Domain state
    user_context: UserTasteContext
    query_spec: RecQuerySpec | None = None
    candidates: list[Candidate] = []
    final_recs: list[FinalRec] = []
    final_summary: str | None = None

    # Control
    step_count: int = 0
    max_steps: int = 3
    done: bool = False

    # Telemetry / traces
    ctx_log: dict[str, Any] | None = None  # whatever you log today
    pipeline_traces: list[dict[int, ScoreTrace]] = []  # dense/sparse/meta traces, etc.
    agent_trace: list[dict[str, Any]] = []  # sequence of tool calls
    meta: dict[str, Any] = {}  # recipe, versions, etc.

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
        user_msg_content = cls._build_initial_user_message(agent_input)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": REC_AGENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg_content},
        ]

        return cls(
            user_id=agent_input.user_id,
            query_id=agent_input.query_id,
            session_id=agent_input.session_id,
            media_type=str(agent_input.media_type) if agent_input.media_type else None,
            device_info=agent_input.device_info,
            messages=messages,
            user_context=user_context,
        )

    @staticmethod
    def _build_initial_user_message(agent_input: InteractiveAgentInput) -> str:
        """
        Normalize the HTTP request into a single user message string
        that includes both free-text query and structured filters.
        """
        parts: list[str] = []

        if agent_input.query_text:
            parts.append(f"User query: {agent_input.query_text}")

        if agent_input.media_type:
            parts.append(f"Media type: {agent_input.media_type}")

        if agent_input.query_filters:
            parts.append("Structured filters (JSON):")
            # you can safely stringify; model will still parse it fine
            import json

            filters = (
                agent_input.query_filters.model_dump()
                if hasattr(agent_input.query_filters, "model_dump")
                else agent_input.query_filters
            )
            parts.append(json.dumps(filters, ensure_ascii=False))

        # Fallback if nothing was set
        if not parts:
            parts.append("User is asking for personalized recommendations.")

        return "\n\n".join(parts)

    async def execute_tool_call(
        self,
        *,
        decision: LlmDecision,
        agent_rec_runner: AgentRecRunner,
        user_context_service,
        llm_client,
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

        if tool_name == "call_rec_engine":
            await self._exec_call_rec_engine(tool_call_id, tool_args, agent_rec_runner=agent_rec_runner)
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

    async def _exec_call_rec_engine(
        self, tool_call_id, tool_args: dict[str, Any], agent_rec_runner: AgentRecRunner
    ) -> None:
        """
        Handle call_rec_engine(rec_query_spec=...).
        """
        # 1) Parse RecQuerySpec from tool args
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
            )

        candidates, traces, ctx_log = await to_thread.run_sync(_run_agent_sync)

        self.candidates = candidates
        if traces:
            self.pipeline_traces.append(traces)
        if ctx_log:
            self.ctx_log = ctx_log

        # 4) Prepare a light-weight view for the LLM (avoid huge payloads)
        view = [
            c.payload.get("llm_context", "")
            for c in candidates[:20]  # limit for token cost
        ]
        tool_payload = {
            "count": len(candidates),
            "top_candidates": view,
        }
        
        print (tool_payload)

        # 5) Record trace + append tool result message
        self.agent_trace.append(
            {
                "step": self.step_count,
                "tool": "call_rec_engine",
                "args": tool_args,
                "result": {"count": len(candidates)},
            }
        )
        self.messages.append(
            {
                "role": "tool",
                "name": "call_rec_engine",
                "tool_call_id": tool_call_id,
                "content": json.dumps(tool_payload),
            }
        )