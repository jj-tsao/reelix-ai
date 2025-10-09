from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import List, Iterable, Tuple, Annotated, Dict, Any
from pydantic import BaseModel, Field, AfterValidator

MediaId = int


class MediaType(str, Enum):
    MOVIE = "movie"
    TV = "tv"


def _validate_years(t: Tuple[int, int]) -> Tuple[int, int]:
    start, end = t
    if start > end:
        raise ValueError("year_range start must be <= end")
    if start < 1878 or end > 2100:  # arbitrary sanity bounds
        raise ValueError("year_range is out of reasonable bounds")
    return t


YearRange = Annotated[Tuple[int, int], AfterValidator(_validate_years)]


class QueryFilter(BaseModel):
    genres: list[str] = Field(default_factory=list, examples=[[]])
    providers: list[int] = Field(default_factory=list, examples=[[]])
    year_range: YearRange = (1970, 2025)


@dataclass
class Interaction:
    media_type: str  # 'movie' | 'tv'
    media_id: MediaId  # tmdb id
    title: str
    kind: str  # 'love' | 'like' | 'dislike'
    ts: datetime  # tz-aware


@dataclass
class UserSignals:
    genres_include: list[str]
    keywords_include: list[str]
    interactions: list[Interaction]
    exclude_media_ids: list[int]

    def _by_kind(self, kinds: Iterable[str]) -> List[Interaction]:
        kinds_norm = {k.lower() for k in kinds}
        return [i for i in self.interactions if i.kind.lower() in kinds_norm]

    def positive_interactions(self) -> List[Interaction]:
        """Interactions where kind is 'like' or 'love'."""
        return self._by_kind({"like", "love"})

    def loved_titles(self) -> List[Interaction]:
        """Interactions where kind is 'love'."""
        return self._by_kind({"love"})

    def liked_titles(self) -> List[Interaction]:
        """Interactions where kind is 'like'."""
        return self._by_kind({"like"})

    def disliked_titles(self) -> List[Interaction]:
        """Interactions where kind is 'dislike'."""
        return self._by_kind({"dislike"})


@dataclass
class UserTasteContext:
    taste_vector: list[float] | None
    positive_n: int | None
    negative_n: int | None
    last_built_at: datetime | None
    signals: UserSignals
    active_subscriptions: list[int]
    provider_filter_mode: str | None


@dataclass
class BuildParams:
    dim: int = 768
    w_love: float = 2.0
    w_like: float = 1.0
    w_dislike: float = 1.5
    lambda_month: float = 0.05  # decay per 30 days (half-life = 12 months)
    alpha: float = 1.0  # +pos centroid
    beta: float = 0.6  # −neg centroid
    gamma: float = 0.2  # genre/vibe prior
    delta: float = 0.15  # keyword prior
    min_pos_for_profile: int = 1
    min_total_for_profile: int = 2


class PromptsEnvelope(BaseModel):
    model: str
    params: Dict[str, Any] = Field(
        default_factory=dict
    )  # temp/top_p/seed/max_tokens, etc.
    recipe: Dict[str, Any] = Field(default_factory=dict)
    output: Dict[str, Any] = Field(default_factory=lambda: {"format":"jsonl","schema_version":"1"})
    calls: list["LLMCall"] = Field(
        default_factory=list
    )  # one or many calls with caching
    prompt_hash: str  # sha256 of (mode, calls.messages, model, params)
    created_at: float


class LLMCall(BaseModel):
    call_id: int | None
    messages: List[
        Dict[str, Any]
    ]  # [{"role":"system","content":...}, {"role":"user","content":...}] pair
    items_brief: List[Dict[str, Any]] = Field(
        default_factory=list
    )  # [{"media_id","title"}, ...] (for logs)
