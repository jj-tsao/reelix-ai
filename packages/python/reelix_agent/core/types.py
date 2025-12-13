from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict
from reelix_core.types import MediaType, QueryFilter
from reelix_ranking.types import Candidate
from reelix_user_context.user_context_service import UserContextService


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
    candidates: list[Candidate]
    final_recs: list[Candidate]
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
    core_genres: list[str] = []
    exclude_genres: list[str] = []
    sub_genres: list[str] = []
    core_tone: list[str] = []
    narrative_shape: list[str] = []
    providers: list[str] = []  # e.g. ["netflix", "hulu"]
    year_range: tuple[int, int] = (1970, 2025)
    query_filters: QueryFilter | None = None
    max_runtime_minutes: int | None = None
    min_rating: float | None = None
    tone: str | None = None  # "not too dark", "cozy", etc
    num_recs: int = 8


class LlmDecision(AgentBaseModel):
    """
    Normalized result of a single LLM call with tools.
    """

    is_tool_call: bool
    content: str | None = None
    tool_name: str | None = None  # function name if is_tool_call=True
    tool_args: dict[str, Any] = {}  # parsed JSON args if is_tool_call=True
    tool_call_id: str | None = None  # id for the tool call (OpenAI API)
