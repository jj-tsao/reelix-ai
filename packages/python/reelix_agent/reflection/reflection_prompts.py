from __future__ import annotations

from collections import Counter
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
            " corner of cinema that shares the same thread but these results don't cover."
            " Reference titles from the current results to ground the observation."
        ),
        "examples": [
            '{"strategy": "follow_the_thread", "suggestion": "Isolation and paranoia run through all of these. Want to follow that thread into cosmic horror — same claustrophobic dread but with an alien or unknowable force driving it?"}',
            '{"strategy": "follow_the_thread", "suggestion": "Every pick here uses an unreliable narrator to keep you guessing. Want to follow that into puzzle-box films where the structure itself is the twist?"}',
        ],
    },
    "reframe": {
        "description": (
            "Keep the core appeal but repackage it in a completely different context — swap the"
            " tone, decade, or setting. Describe the destination vibe concretely instead of"
            " naming titles the user may not know."
        ),
        "examples": [
            '{"strategy": "reframe", "suggestion": "These are all set in sprawling cities. Want the same tension and isolation but in a small-town setting — tight community, nowhere to hide, everyone\'s a suspect?"}',
            '{"strategy": "reframe", "suggestion": "These all land in the 2010s. Want this same vibe in 90s sci-fi? Grittier, more paranoid, and lo-fi in the best way."}',
        ],
    },
    "wildcard": {
        "description": (
            "Find the deeper emotional or structural quality driving these results, then propose"
            " a completely different genre that shares it. Describe the destination vibe"
            " concretely instead of naming titles the user may not know. The connection should"
            " feel surprising but immediately click once explained."
        ),
        "examples": [
            '{"strategy": "wildcard", "suggestion": "What hooks you in these heist films is watching experts improvise under pressure. Want to try disaster films where that same competence-under-chaos is the real spectacle?"}',
            '{"strategy": "wildcard", "suggestion": "The dread in these horror picks isn\'t the monsters — it\'s being stuck in a system that doesn\'t care about you. Want to see that same nightmare played as dark comedy — bureaucratic absurdity turned up to eleven?"}',
        ],
    },
}

STRATEGY_NAMES = list(STRATEGIES.keys())


def _build_weighting_guidance(recent_strategies: list[str]) -> str:
    """Build soft weighting guidance based on recent strategy history."""
    if not recent_strategies:
        return "Pick whichever strategy best fits the results."

    last = recent_strategies[-1]
    hard_block = f"Do NOT use **{last}** — you used it last turn."

    counts = Counter(recent_strategies)
    unused = [s for s in STRATEGY_NAMES if counts[s] == 0 and s != last]

    if unused:
        names = " or ".join(f"**{s}**" for s in unused)
        return f"{hard_block} Prefer {names} this turn — they'll bring fresh perspective."

    # All strategies used at least once; prefer the least used (excluding last)
    min_count = min(counts[s] for s in STRATEGY_NAMES if s != last)
    least_used = [s for s in STRATEGY_NAMES if counts[s] == min_count and s != last]
    names = " or ".join(f"**{s}**" for s in least_used)
    return f"{hard_block} Prefer {names} this turn — they'll bring fresh perspective."


def _pick_examples(recent_strategies: list[str]) -> str:
    """Pick 2 examples: one from a preferred (underused) strategy, one from another."""
    counts = Counter(recent_strategies)
    unused = [s for s in STRATEGY_NAMES if counts[s] == 0]

    if unused:
        preferred = unused[0]
    else:
        min_count = min(counts[s] for s in STRATEGY_NAMES)
        preferred = next(s for s in STRATEGY_NAMES if counts[s] == min_count)

    # Pick a second strategy that's different from preferred
    other = next(s for s in STRATEGY_NAMES if s != preferred)

    return "\n".join([
        STRATEGIES[preferred]["examples"][0],
        STRATEGIES[other]["examples"][0],
    ])


REFLECTION_SYS_PROMPT_TEMPLATE = """\
You are a film curator for Reelix. After each set of recommendations, you propose ONE clear
next direction for the user to explore. Pick the strategy that best fits the results.

## Strategies

deep_dive — {deep_dive_desc}
follow_the_thread — {follow_the_thread_desc}
reframe — {reframe_desc}
wildcard — {wildcard_desc}

## Guidance this turn

{weighting_guidance}

## Output format
ONLY valid JSON, no markdown:
{{"strategy": "<name>", "suggestion": "<1-2 sentences>"}}

## How to write the suggestion

Structure: [brief observation about the results] + [proposal question ending with "?"]

The proposal must be specific enough that when the user says "yes", we know exactly what to
search for. It must name a concrete anchor — a sub-genre, reference title, decade, setting,
or vivid descriptor. Never use broad categories alone.

Tone: professional film curator — knowledgeable, confident, concise.

## Examples

GOOD:
{examples}

BAD — vague categories, no concrete anchor:
{{"strategy": "follow_the_thread", "suggestion": "Dark comedy runs through these thrillers. I'd guide you to films that blend satire with social commentary, diving into the absurdities of modern life."}}
"""


def build_reflection_sys_prompt(recent_strategies: list[str] | None = None) -> str:
    """Build the system prompt with all strategies and soft weighting guidance."""
    recent = recent_strategies or []
    return REFLECTION_SYS_PROMPT_TEMPLATE.format(
        deep_dive_desc=STRATEGIES["deep_dive"]["description"],
        follow_the_thread_desc=STRATEGIES["follow_the_thread"]["description"],
        reframe_desc=STRATEGIES["reframe"]["description"],
        wildcard_desc=STRATEGIES["wildcard"]["description"],
        weighting_guidance=_build_weighting_guidance(recent),
        examples=_pick_examples(recent),
    )


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
