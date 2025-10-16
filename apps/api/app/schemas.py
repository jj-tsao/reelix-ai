from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field, field_validator
from reelix_core.types import MediaType, QueryFilter


class ChatMessage(BaseModel):
    role: str
    content: str


class DeviceInfo(BaseModel):
    device_type: str | None = None
    platform: str | None = None
    user_agent: str | None = None


class DiscoverRequest(BaseModel):
    media_type: MediaType = MediaType.MOVIE
    page: int = 1
    page_size: int = 20
    include_llm_why: bool = False  # if true, returns markdown “why” in JSON
    session_id: str
    query_id: str
    device_info: DeviceInfo | None = None


class InteractiveRequest(BaseModel):
    media_type: MediaType = MediaType.MOVIE
    query_text: str = Field(
        ...,
        examples=[
            "Mind-bending sci-fi with philosophical undertones and existential stakes"
        ],
    )
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