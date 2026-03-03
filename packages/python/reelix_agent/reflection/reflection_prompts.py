from __future__ import annotations

import random
from typing import Any

from reelix_agent.core.types import RecQuerySpec
from reelix_ranking.types import Candidate

STRATEGIES: dict[str, dict[str, Any]] = {
    "deep_dive": {
        "description": (
            "Zoom into one title's specific quality — its sub-genre, directorial style, or"
            " narrative approach. Always name the title."
        ),
        "examples": [
            '{"strategy": "deep_dive", "suggestion": "Nightcrawler is the standout here. Want to go deeper into LA noir with morally bankrupt protagonists and that same hustle-or-die energy?"}',
            '{"strategy": "deep_dive", "suggestion": "The Lobster has a very specific deadpan absurdist tone. Want to lean into that Yorgos Lanthimos vein — cold, surreal, and wickedly dry?"}',
        ],
    },
    "follow_the_thread": {
        "description": (
            "Name a pattern across the results, then propose where it leads — a different"
            " corner of cinema that shares the same thread."
        ),
        "examples": [
            '{"strategy": "follow_the_thread", "suggestion": "Isolation and paranoia run through all of these. Want to follow that thread into cosmic horror — Lovecraftian dread in confined spaces, like Annihilation or The Thing?"}',
            '{"strategy": "follow_the_thread", "suggestion": "Class tension and power dynamics keep showing up. Want to follow that into workplace thrillers — corporate hierarchies as horror, like The Assistant or Margin Call?"}',
        ],
    },
    "reframe": {
        "description": (
            "Keep the core appeal but repackage it in a completely different context — swap the"
            " tone, decade, or setting. Name a reference title in the current recs to anchor the shift."
        ),
        "examples": [
            '{"strategy": "reframe", "suggestion": "These are all set in sprawling cities. Want the same tension and isolation but in a small-town setting — more Wind River than Sicario?"}',
            '{"strategy": "reframe", "suggestion": "These all land in the 2010s. Want this same vibe in 90s sci-fi? Grittier, more paranoid, and lo-fi in the best way."}',
        ],
    },
    "wildcard": {
        "description": (
            "Propose something the user would never search for themselves but that connects to"
            " these results in a non-obvious way. Name the specific title or niche and explain the link."
        ),
        "examples": [
            '{"strategy": "wildcard", "suggestion": "Hear me out — the moral ambiguity and obsessive drive here has the same energy as chef movies like Burnt or The Hundred-Foot Journey. High stakes, perfectionist protagonists. Want to try that?"}',
            '{"strategy": "wildcard", "suggestion": "These dark thrillers share a visual DNA with neo-noir anime — think Perfect Blue or Monster. Want to explore that unexpected crossover?"}',
        ],
    },
}

STRATEGY_NAMES = list(STRATEGIES.keys())

REFLECTION_SYS_PROMPT_TEMPLATE = """\
You are a film curator for Reelix. After each set of recommendations, you propose ONE clear
next direction for the user to explore.

## Your strategy: {strategy}

{strategy_description}

## Output format
ONLY valid JSON, no markdown:
{{"strategy": "{strategy}", "suggestion": "<1-2 sentences>"}}

## How to write the suggestion

Structure: [brief observation about the results] + [proposal question ending with "?"]

The proposal must be specific enough that when the user says "yes", we know exactly what to
search for. It must name a concrete anchor — a sub-genre, reference title, decade, setting,
or vivid descriptor. Never use broad categories alone.

Tone: professional film curator — knowledgeable, confident, concise.

## Examples

GOOD:
{strategy_examples}

BAD — vague categories, no concrete anchor:
{{"strategy": "{strategy}", "suggestion": "Dark comedy runs through these thrillers. I'd guide you to films that blend satire with social commentary, diving into the absurdities of modern life."}}
"""


def build_reflection_sys_prompt(strategy: str) -> str:
    """Build the system prompt for a specific strategy."""
    info = STRATEGIES[strategy]
    return REFLECTION_SYS_PROMPT_TEMPLATE.format(
        strategy=strategy,
        strategy_description=info["description"],
        strategy_examples="\n".join(info["examples"]),
    )


def pick_strategy(previous_strategy: str | None = None) -> str:
    """Pick a random strategy, excluding the previous one."""
    available = [s for s in STRATEGY_NAMES if s != previous_strategy]
    return random.choice(available)


def build_reflection_user_prompt(
    *,
    query_spec: RecQuerySpec,
    final_recs: list[Candidate],
    tier_stats: dict[str, Any] | None = None,
) -> str:
    parts: list[str] = []

    # USER REQUEST section
    parts.append("USER REQUEST")
    query_text = (query_spec.query_text or "").strip()
    if query_text:
        parts.append(f"query_text: {query_text}")

    genres = (query_spec.core_genres or []) + (query_spec.sub_genres or [])
    if genres:
        parts.append(f"genres: {', '.join(genres)}")

    if query_spec.core_tone:
        parts.append(f"tone: {', '.join(query_spec.core_tone)}")

    if query_spec.key_themes:
        parts.append(f"themes: {', '.join(query_spec.key_themes)}")

    parts.append("")

    # RESULTS RETURNED section
    parts.append("RESULTS RETURNED")

    served_count = len(final_recs)
    strong_count = 0
    moderate_count = 0
    if tier_stats:
        strong_count = tier_stats.get("strong_count", 0)
        moderate_count = tier_stats.get("moderate_count", 0)

    parts.append(
        f"served: {served_count} titles ({strong_count} strong matches, {moderate_count} moderate matches)"
    )

    for c in final_recs:
        payload = c.payload or {}
        ctx = payload.get("llm_context") or {}
        title = ctx.get("t") or payload.get("title") or payload.get("name") or "Unknown"
        genres = ctx.get("g") or []
        keywords = ctx.get("k") or []
        overview = ctx.get("o") or ""
        line = f"- {title}"
        if genres:
            line += f" | g: {', '.join(genres)}"
        if keywords:
            line += f" | k: {', '.join(keywords[:6])}"
        if overview:
            line += f" | o: {overview[:120]}"
        parts.append(line)

    parts.append("")
    parts.append("Propose ONE concrete next direction as a question the user can say yes to.")

    return "\n".join(parts)
