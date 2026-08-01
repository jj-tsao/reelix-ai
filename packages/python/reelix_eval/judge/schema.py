"""Structured-output models for the LLM judge.

These pydantic models *are* the JSON schema handed to the Anthropic API via
`client.messages.parse(output_format=...)`, so the model's output is validated
before it reaches us. The original judge did a bare `json.loads` with a silent
fallback to `{}` — a malformed response scored every candidate as `None` and
looked, in aggregate, exactly like a quality regression.

Scores use `Literal` rather than `Field(ge=1, le=5)` deliberately: structured
outputs support `enum` but not numeric constraints, so a `Literal` becomes a hard
constraint the model cannot violate, while `ge`/`le` would be stripped from the
schema and only checked client-side.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Score = Literal[1, 2, 3, 4, 5]


class RecItemVerdict(BaseModel):
    """Judgement of a single recommendation, made without seeing its "why" text."""

    media_id: int = Field(description="Must be one of the media_ids given in the input.")
    relevance: Score = Field(description="How well this title answers the request.")
    novelty: Score = Field(description="How non-obvious this pick is.")
    spec_violation: bool = Field(
        description=(
            "True if this title breaks a HARD constraint in the spec: an excluded "
            "genre, a year outside year_range, or a provider not in the requested "
            "list. Soft preferences (tone, themes) are never violations."
        )
    )
    reasoning: str = Field(description="One sentence justifying relevance and novelty.")


class RecQualityVerdict(BaseModel):
    """Output of judge call 1 — the curator's picks, judged blind to explanations."""

    items: list[RecItemVerdict]
    spec_fidelity: Score = Field(
        description=(
            "How faithfully the orchestrator's structured spec captured the user's "
            "actual request. Judges the spec, not the titles."
        )
    )
    list_coherence: Score = Field(
        description=(
            "How well the served titles work as one set: varied enough to be worth "
            "browsing, consistent enough to read as a deliberate answer."
        )
    )
    query_reasoning: str = Field(
        description="One or two sentences on the spec and the slate as a whole."
    )


class ExplanationItemVerdict(BaseModel):
    """Judgement of a single 'why you'll like it' explanation."""

    media_id: int = Field(description="Must be one of the media_ids given in the input.")
    explanation_quality: Score = Field(
        description="How specific and persuasive the explanation is."
    )
    explanation_grounded: bool = Field(
        description=(
            "True if every factual claim about the title is accurate. False if it "
            "asserts anything contradicted by the metadata or invents plot, cast, "
            "or themes."
        )
    )
    reasoning: str = Field(description="One sentence justifying the score.")


class ExplanationQualityVerdict(BaseModel):
    """Output of judge call 2 — the explanation agent, judged with the why text."""

    items: list[ExplanationItemVerdict]