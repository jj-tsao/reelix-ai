"""Judge rubrics and prompt builders.

Two independent calls per query, deliberately separated so the two agents stay
distinguishable:

1. **Recommendation quality** — judges the curator's picks *without* the "why"
   text, so a persuasive explanation can't rescue a bad pick.
2. **Explanation quality** — judges the explanation agent *with* the why text.

If relevance drops, look at the curator. If explanation quality drops, look at
the explanation agent. The original rubrics were bare 1-5 scales tuned against
`gpt-4o-mini`; these add explicit anchors per point so scores mean the same thing
across judge-model changes.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from reelix_eval.store import CandidateDetail, QueryDetail


REC_JUDGE_SYSTEM = """\
You are a demanding evaluator of movie recommendations. You are shown a user's \
request, the structured spec a planning agent derived from it, and the titles a \
recommender served — each with its real metadata. You are NOT shown the system's \
explanations. Judge the picks themselves.

Score every title on two 1-5 scales.

relevance — does this title answer what the user actually asked for?
  1  Unrelated. Shares no meaningful genre, tone, or theme with the request.
  2  Tangential. One superficial link, but nobody asking this would want it.
  3  Partial. Genuinely matches some of the request and misses the rest.
  4  Strong. Matches the request with a minor gap in tone, era, or emphasis.
  5  Exact. Matches genre, tone, and theme; an obvious yes for this request.

novelty — how non-obvious is this pick, GIVEN that it is relevant?
  1  The single most predictable title for this request.
  2  Well-known, top-of-mind for anyone who knows the genre.
  3  Recognizable but not the first thing most people would name.
  4  Off the beaten path; a knowledgeable friend's suggestion.
  5  Genuinely surprising and still a real fit.
  Never raise novelty because a title is irrelevant. Obscure and wrong is a 1.

spec_violation — a HARD constraint is broken. Set true only when the title's \
metadata contradicts an explicit spec constraint: a genre listed in \
exclude_genres, a release year outside year_range, or a provider outside the \
requested providers. Tone, themes, and sub-genres are soft preferences — \
never a violation. When the metadata needed to check is missing, use false.

Then score the request as a whole.

spec_fidelity — did the planning agent's spec capture the user's request?
  1  Contradicts the request or drops its central ask.
  2  Captures a fragment; the main intent is missing or distorted.
  3  Broadly right, but loses a qualifier that changes what should be served.
  4  Accurate; a minor nuance is under-weighted.
  5  Faithful, including tone and constraints. Nothing invented.
  Judge the spec against the request only — ignore whether the titles are good.

list_coherence — do the served titles work as ONE answer?
  1  Near-duplicates, or an incoherent grab bag.
  2  Heavy redundancy — several titles are interchangeable.
  3  Acceptable, with one visible cluster of repetition.
  4  Varied, with a clear through-line to the request.
  5  Each title earns its slot and adds an angle the others don't.

Judge only what the metadata supports. Do not invent facts about a title. If you \
do not recognize a title, judge it from the metadata given.
Use only media_ids that appear in the input."""


EXPL_JUDGE_SYSTEM = """\
You are evaluating personalized "why you'll enjoy it" explanations for movie \
recommendations. You are shown the user's request, each recommended title with \
its real metadata, and the explanation the system generated.

Judge the explanation, not the pick. A weak recommendation can carry an \
excellent explanation, and vice versa — score what is written.

explanation_quality (1-5)
  1  Generic. Would apply unchanged to any other title.
  2  Names the title but never connects it to this user's request.
  3  Connects to the request, but only restates the genre or premise.
  4  Specific and persuasive; points at what in this title answers the request.
  5  Insightful; surfaces a real, non-obvious link the user would not have made.

explanation_grounded (bool) — is every factual claim about the title true?
  Set false when the explanation contradicts the metadata, or invents plot \
  points, characters, cast, or themes not supported by it. Subjective claims \
  ("gripping", "quietly devastating") are not grounding failures. Vague but \
  accurate is grounded and simply scores low on quality.
  This is a hallucination check — an explanation can be persuasive and ungrounded.

Use only media_ids that appear in the input."""


def _provider_names(ids: list) -> list[str]:
    """TMDB provider IDs → display names for the prompt.

    Payloads store integer IDs; showing the judge `257, 583` instead of
    `Netflix, Hulu` tells it nothing and makes provider constraints unjudgeable.
    Unknown IDs are dropped rather than shown raw.
    """
    try:
        from reelix_retrieval.qdrant_filter import WATCH_PROVIDERS
    except ImportError:
        return []

    by_id = {pid: name for name, pid in WATCH_PROVIDERS.items()}
    out: list[str] = []
    for i in ids:
        try:
            name = by_id.get(int(i))
        except (TypeError, ValueError):
            continue
        if name:
            out.append(name)
    return out


def _spec_block(spec: dict | None) -> str:
    if not spec:
        return ""

    keep = (
        "query_text",
        "core_genres",
        "exclude_genres",
        "sub_genres",
        "core_tone",
        "key_themes",
        "providers",
        "year_range",
    )
    payload = {k: spec[k] for k in keep if spec.get(k)}
    if not payload:
        return ""
    return "\n\nSpec produced by the planning agent:\n" + json.dumps(
        payload, indent=2, ensure_ascii=False
    )


def _candidate_block(c: "CandidateDetail", index: int, include_why: bool) -> str:
    lines = [f"{index}. {c.title} (media_id: {c.media_id})"]
    if c.release_year:
        lines.append(f"   year: {c.release_year}")
    if c.genres:
        lines.append(f"   genres: {', '.join(str(g) for g in c.genres)}")
    if c.keywords:
        lines.append(f"   keywords: {', '.join(str(k) for k in c.keywords)}")
    providers = _provider_names(c.watch_providers)
    if providers:
        lines.append(f"   providers: {', '.join(providers)}")
    if c.overview:
        lines.append(f"   overview: {c.overview}")
    if include_why and c.why_summary:
        lines.append(f"   why shown to user: {c.why_summary}")
    return "\n".join(lines)


def build_rec_prompt(detail: "QueryDetail") -> str:
    """User prompt for judge call 1 — no "why" text included."""
    served = detail.served
    blocks = [_candidate_block(c, i, include_why=False) for i, c in enumerate(served, 1)]
    return (
        f'User request: "{detail.query_text}"'
        f"{_spec_block(detail.spec_json)}\n\n"
        f"Titles served ({len(served)}):\n" + "\n\n".join(blocks)
    )


def build_expl_prompt(detail: "QueryDetail") -> str:
    """User prompt for judge call 2 — only titles that actually have why text.

    Returns "" when the explanation agent produced nothing for this query, which
    is the signal to skip the call rather than score absent text as bad.
    """
    served = [c for c in detail.served if c.why_summary]
    if not served:
        return ""

    blocks = [_candidate_block(c, i, include_why=True) for i, c in enumerate(served, 1)]
    return (
        f'User request: "{detail.query_text}"'
        f"{_spec_block(detail.spec_json)}\n\n"
        f"Recommendations with their explanations ({len(served)}):\n"
        + "\n\n".join(blocks)
    )