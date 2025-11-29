from __future__ import annotations

from enum import Enum
from typing import List, Dict, Any
from pydantic import BaseModel

from interactive.prompts import SYSTEM_PROMPT
from reelix_core.types import MediaType, UserTasteContext, QueryFilter
from reelix_ranking.types import Candidate
from reelix_user_context.user_context_service import UserContextService


class InteractiveAgentInput(BaseModel):
    user_id: str
    query_id: str
    session_id: str | None
    media_type: MediaType
    query_text: str
    query_filters: QueryFilter
    user_context_service: UserContextService
    batch_size: int = 20
    device_info: dict | None = None


class InteractiveAgentResult(BaseModel):
    final_recs: List[FinalRec]
    summary: str
    ctx_log: dict | None = None
    pipeline_traces: List[dict] = []
    agent_trace: List[dict] = []
    meta: dict = {}


class AgentMode(str, Enum):
    RECS = "recs"  # default
    # EXPLAIN = "explain"    # "why this / why not that"
    PREFS = "preferences"  # set preferences


class RecQuerySpec(BaseModel):
    mode: AgentMode = AgentMode.RECS
    query_text: str | None = None  # raw NL query / vibes
    seed_titles: List[int] = []  # TMDB IDs etc
    include_genres: List[str] = []
    exclude_genres: List[str] = []
    include_keywords: List[str] = []
    exclude_keywords: List[str] = []
    providers: List[str] = []  # e.g. ["netflix", "hulu"]
    max_runtime_minutes: int | None = None
    min_rating: float | None = None
    tone: str | None = None  # "not too dark", "cozy", etc
    limit: int = 20


class FinalRec(BaseModel):
    media_id: int
    title: str
    media_type: str
    overview: str
    providers: List[str]
    score: float
    why: str | None = None


class AgentState(BaseModel):
    # IDs / metadata
    user_id: str
    query_id: str
    session_id: str | None = None
    media_type: str | None = None  # or your MediaType enum
    device_info: Dict[str, Any] | None = None

    # LLM conversational state
    messages: List[Dict[str, Any]] = []

    # Domain state
    user_context: UserTasteContext
    query_spec: RecQuerySpec | None = None
    candidates: List[Candidate] = []
    final_recs: List[FinalRec] = []
    final_summary: str | None = None

    # Control
    step_count: int = 0
    max_steps: int = 4
    done: bool = False

    # Telemetry / traces
    ctx_log: Dict[str, Any] | None = None  # whatever you log today
    pipeline_traces: List[Dict[str, Any]] = []  # dense/sparse/meta traces, etc.
    agent_trace: List[Dict[str, Any]] = []  # sequence of tool calls
    meta: Dict[str, Any] = {}  # recipe, versions, etc.

    @classmethod
    def from_agent_input(cls, agent_input: InteractiveAgentInput, user_context: UserTasteContext) -> "AgentState":
        """
        Bootstrap a fresh AgentState from the HTTP-level input.

        Called at the start of an interactive agent run
        (new query_id / session), before any tools are invoked.
        """
        # Build the initial user message content the LLM sees
        user_msg_content = cls._build_initial_user_message(agent_input)

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
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
            # everything else uses defaults (None / [] / 0 / False)
        )

    @staticmethod
    def _build_initial_user_message(agent_input: InteractiveAgentInput) -> str:
        """
        Normalize the HTTP request into a single user message string
        that includes both free-text query and structured filters.
        """
        parts: List[str] = []

        if agent_input.query_text:
            parts.append(f"User query: {agent_input.query_text}")

        if agent_input.media_type:
            parts.append(f"Media type: {agent_input.media_type}")

        if agent_input.query_filters:
            parts.append("Structured filters (JSON):")
            # you can safely stringify; model will still parse it fine
            import json

            parts.append(json.dumps(agent_input.query_filters, ensure_ascii=False))

        # Fallback if nothing was set
        if not parts:
            parts.append("User is asking for personalized recommendations.")

        return "\n\n".join(parts)
