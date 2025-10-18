from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class WatchStatus(str, Enum):
    WANT = "want"
    WATCHED = "watched"


class WatchlistCreate(BaseModel):
    user_id: str
    media_id: int
    media_type: Literal["movie", "tv"]
    status: WatchStatus = WatchStatus.WANT
    title: str | None = None
    poster_url: str | None = None
    backdrop_url: str | None = None
    release_year: int | None = None
    genres: list[str] | None = None
    source: str | None = None


class WatchlistUpdate(BaseModel):
    user_id: str
    id: str
    media_id: int | None = None
    status: WatchStatus | None = None
    rating: int | None = Field(default=None, ge=1, le=10)
    notes: str | None = None


class WatchlistRemoveById(BaseModel):
    user_id: str
    id: str


class ExistsOut(BaseModel):
    exists: bool
    id: str | None = None
    status: WatchStatus = WatchStatus.WANT
    rating: int | None = None


class WatchlistItem(BaseModel):
    user_id: str
    id: str
    media_id: int
    media_type: str
    status: WatchStatus
    rating: int | None = None
    notes: str | None = None
    title: str | None = None
    poster_url: str | None = None
    backdrop_url: str | None = None
    release_year: int | None = None
    genres: list[str] | None = None
    source: str | None = None
    created_at: str
    updated_at: str
    deleted_at: str | None = None
    is_active: bool
