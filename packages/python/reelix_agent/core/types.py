from __future__ import annotations

from enum import Enum
from typing import List, Dict, Any
from pydantic import BaseModel

from reelix_core.types import UserTasteContext
from reelix_ranking.types import Candidate


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
    """State passed through the orchestration loop."""

    user_id: str
    messages: List[Dict[str, Any]] = []  # chat history for the LLM
    user_context: UserTasteContext | None = None
    query_spec: RecQuerySpec | None = None
    candidates: List[Candidate] = []
    final_recs: List[FinalRec] = []
    step_count: int = 0
    max_steps: int = 4
