from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field, field_validator
from reelix_core.types import MediaType, QueryFilter, UserTasteContext


class ChatMessage(BaseModel):
    role: str
    content: str


class DeviceInfo(BaseModel):
    device_type: str | None = None
    platform: str | None = None
    user_agent: str | None = None


class DiscoverRequest(BaseModel):
    user_id: str | None
    media_type: MediaType = MediaType.MOVIE
    user_context: UserTasteContext
    page: int = 1
    page_size: int = 20
    include_llm_why: bool = False  # if true, returns markdown “why” in JSON


class InteractiveRequest(BaseModel):
    media_type: MediaType = MediaType.MOVIE
    query_text: str = Field(..., examples=["Mind-bending sci-fi with philosophical undertones and existential stakes"])
    history: List[ChatMessage] | None = Field(default_factory=list, examples=[[]])
    query_filters: QueryFilter = Field(default_factory=QueryFilter)
    session_id: str
    query_id: str
    device_info: DeviceInfo | None = None

    @field_validator("query_text")
    def validate_question(cls, v):
        if not v.strip():
            raise ValueError("Query cannot be empty")
        return v


class FinalRec(BaseModel):
    media_id: int
    why: str


class FinalRecsRequest(BaseModel):
    query_id: str
    final_recs: List[FinalRec]


# ===== User Taste Profile =====

# class PreferencesUpdate(BaseModel):
#     genres_include: Optional[List[str]] = None
#     genres_exclude: Optional[List[str]] = None
#     keywords_include: Optional[List[str]] = None
#     keywords_exclude: Optional[List[str]] = None
#     languages: Optional[List[str]] = None
#     year_min: Optional[int] = None
#     year_max: Optional[int] = None
#     runtime_min: Optional[int] = None
#     runtime_max: Optional[int] = None
#     maturity_ratings: Optional[List[str]] = None
#     include_movies: Optional[bool] = None
#     include_tv: Optional[bool] = None
#     prefer_recency: Optional[bool] = None
#     diversity_level: Optional[int] = Field(
#         None, description="0=strict,1=balanced,2=explore"
#     )

#     @model_validator(mode="after")
#     def validate_ranges(self) -> "PreferencesUpdate":
#         if self.year_min is not None and self.year_max is not None:
#             if self.year_min > self.year_max:
#                 raise ValueError("year_min must be <= year_max")
#         if self.runtime_min is not None and self.runtime_max is not None:
#             if self.runtime_min > self.runtime_max:
#                 raise ValueError("runtime_min must be <= runtime_max")
#         if self.diversity_level is not None and self.diversity_level not in (0, 1, 2):
#             raise ValueError("diversity_level must be 0, 1, or 2")
#         return self


# class SubscriptionUpsert(BaseModel):
#     provider_id: str
#     active: Optional[bool] = True


# class SubscriptionsPayload(BaseModel):
#     subscriptions: List[SubscriptionUpsert]


# MediaType = Literal["movie", "tv"]

# EventType = Literal[
#     "view",
#     "finish",
#     "like",
#     "dislike",
#     "save",
#     "dismiss",
#     "search",
#     "click",
#     "hover",
#     "trailer_view",
#     "provider_open",
# ]


# class InteractionCreate(BaseModel):
#     media_type: MediaType
#     tmdb_id: int
#     event_type: EventType
#     weight: Optional[float] = 1.0
#     context_json: Optional[Dict[str, Any]] = None
#     occurred_at: Optional[str] = None  # allow client-supplied timestamp


# class InteractionsPayload(BaseModel):
#     interactions: List[InteractionCreate]


# # ===== Recommendation Pipeline =====

# class ChatMessage(BaseModel):
#     role: str
#     content: str


# class MediaType(str, Enum):
#     MOVIE = "movie"
#     TV = "tv"

# class DeviceInfo(BaseModel):
#     device_type: Optional[str] = None
#     platform: Optional[str] = None
#     user_agent: Optional[str] = None


# class ChatRequest(BaseModel):
#     question: str
#     history: List[ChatMessage] = []
#     media_type: MediaType = MediaType.MOVIE
#     genres: List[str] = []
#     providers: List[str] = []
#     year_range: List[int] = [1970, 2025]
#     session_id: str
#     query_id: str
#     device_info: Optional[DeviceInfo] = None

#     @field_validator("question")
#     def validate_question(cls, v):
#         if not v.strip():
#             raise ValueError("Question cannot be empty")
#         return v

#     @model_validator(mode="after")
#     def validate_year_range(self) -> "ChatRequest":
#         if len(self.year_range) != 2:
#             raise ValueError("year_range must be a list of exactly two integers: [start, end]")
#         return self


# class FinalRec(BaseModel):
#     media_id: int
#     why: str


# class FinalRecsRequest(BaseModel):
#     query_id: str
#     final_recs: List[FinalRec]
