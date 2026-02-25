from __future__ import annotations

from typing import Any

from reelix_agent.core.types import RecQuerySpec
from reelix_ranking.types import Candidate


REFLECTION_SYS_PROMPT = """\
You are a film curator for Reelix. After each set of recommendations, you propose ONE clear
next direction for the user to explore. In 1-2 sentences.

## Strategies (pick exactly one)

more_like_title — One title stands out as distinctive or interesting. Propose going deeper into its specific vein.
explore_adjacent — A pattern (keyword, sub-genre, theme) recurs across 3+ results. Propose a sideways pivot.
shift_era — Results cluster in one time period. Propose a specific different decade.

## Output format
ONLY valid JSON, no markdown:
{"strategy": "<name>", "suggestion": "<1-2 sentences>"}

## How to write the suggestion

Structure: [brief observation about the results] + [proposal question ending with "?"]

The proposal must be specific enough that when the user says "yes", we know exactly what to
search for. It must name a concrete anchor — a sub-genre, reference title, decade, setting,
or vivid descriptor. Never use broad categories alone.

Tone: professional film curator — knowledgeable, confident, concise.

## Examples

GOOD:
{"strategy": "explore_adjacent", "suggestion": "Isolation in extreme environments is the through-line here. Want to take that into single-location thrillers — submarines, Arctic stations, deep sea rigs?"}
{"strategy": "shift_era", "suggestion": "These all land in the 2010s. Want to see this same vibe in 70s sci-fi? Grittier, more paranoid, and lo-fi in the best way."}
{"strategy": "explore_adjacent", "suggestion": "Class tension and dark humor run through all of these. Want to go full eat-the-rich — Parasite's tone but across different settings?"}
{"strategy": "more_like_title", "suggestion": "Nightcrawler is the standout here. Want to go deeper into LA noir with morally bankrupt protagonists and that same hustle-or-die energy?"}
{"strategy": "shift_era", "suggestion": "Everything here is post-2000 horror. Want to go back to 80s slashers — more practical effects, campier kills, synth soundtracks?"}

BAD — vague categories, no concrete anchor:
{"strategy": "explore_adjacent", "suggestion": "Dark comedy runs through these thrillers. I'd guide you to films that blend satire with social commentary, diving into the absurdities of modern life."}

BAD — instructs user to search instead of proposing:
{"strategy": "shift_era", "suggestion": "These are all from the 90s. For a fresh take, try searching for 80s neo-noir films that blend synth-heavy soundtracks with crime."}

BAD — passive hedging:
{"strategy": "more_like_title", "suggestion": "If Solaris resonated with you, consider diving deeper into other films that explore psychological aspects of space travel."}
"""


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
    parts.append("Write 1-2 sentences suggesting a specific, actionable next step.")

    return "\n".join(parts)

