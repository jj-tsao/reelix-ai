from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class PreferencesUpdate(BaseModel):
    genres_include: Optional[List[str]] = None
    genres_exclude: Optional[List[str]] = None
    keywords_include: Optional[List[str]] = None
    keywords_exclude: Optional[List[str]] = None
    languages: Optional[List[str]] = None
    year_min: Optional[int] = None
    year_max: Optional[int] = None
    runtime_min: Optional[int] = None
    runtime_max: Optional[int] = None
    maturity_ratings: Optional[List[str]] = None
    include_movies: Optional[bool] = None
    include_tv: Optional[bool] = None
    prefer_recency: Optional[bool] = None
    diversity_level: Optional[int] = Field(
        None, description="0=strict,1=balanced,2=explore"
    )

    @model_validator(mode="after")
    def validate_ranges(self) -> "PreferencesUpdate":
        if self.year_min is not None and self.year_max is not None:
            if self.year_min > self.year_max:
                raise ValueError("year_min must be <= year_max")
        if self.runtime_min is not None and self.runtime_max is not None:
            if self.runtime_min > self.runtime_max:
                raise ValueError("runtime_min must be <= runtime_max")
        if self.diversity_level is not None and self.diversity_level not in (0, 1, 2):
            raise ValueError("diversity_level must be 0, 1, or 2")
        return self


class SubscriptionUpsert(BaseModel):
    provider_id: str
    active: Optional[bool] = True


class SubscriptionsPayload(BaseModel):
    subscriptions: List[SubscriptionUpsert]


MediaType = Literal["movie", "tv"]
EventType = Literal[
    "view",
    "finish",
    "like",
    "dislike",
    "save",
    "dismiss",
    "search",
    "click",
    "hover",
    "trailer_view",
    "provider_open",
]


class InteractionCreate(BaseModel):
    media_type: MediaType
    tmdb_id: int
    event_type: EventType
    weight: Optional[float] = 1.0
    context_json: Optional[Dict[str, Any]] = None
    occurred_at: Optional[str] = None  # allow client-supplied timestamp


class InteractionsPayload(BaseModel):
    interactions: List[InteractionCreate]
