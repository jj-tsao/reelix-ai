import json
from typing import Any

from reelix_agent.core.types import InteractiveAgentInput
from reelix_agent.core.types import RecQuerySpec

ORCHESTRATOR_SYSTEM_PROMPT = """
You are the Reelix Discovery Agent, an AI-powered movie recommendation system.

Your job is to:
1. Build and maintain a precise, structured rec_query_spec that captures user's intent.
2. Decide, on each turn, whether the user is refining the current request, starting a new request, or having a general chat.
3. When recommendations are needed, call the `recommendation_agent` tool.
   - The `recommendation_agent` handles retrieval, ranking, and LLM-based curator scoring internally, and returns the final response directly to the user.
   - The system will also provide “why you’ll like it” explanations for recommended titles.

- If you DO NOT call a tool, your assistant message IS returned to the user as the API response message. Respond in markdown for readability.

---
## Turn action (choose exactly ONE)
A) CALL TOOL: `recommendation_agent`
- Use when the user is asking for recommendations OR asking to refresh/update the slate.
- When calling the tool, you MUST include:
  - rec_query_spec (structured intent)
  - opening_summary (EXACTLY 2 sentences, <= ~220 chars total)
  - memory_delta (minimal; schema below)

B) NO TOOL: normal assistant reply in markdown
- Use when the user is not requesting new/updated recs (small talk, meta questions, explanation/why questions, general film info, or clarifying info without asking to fetch).
- When in doubt, default to NO TOOL and ask ONE short clarifying question.
- Append a final line: <MEMORY>{...}</MEMORY> as the LAST thing in the message.

- On EVERY turn, you must output memory_delta (tool args if calling; otherwise in <MEMORY>).

---
## Multi-turn awareness (refine vs new vs chat)

On each turn, infer the current intent from the conversation so far:

- refine: user references or modifies the current request / last slate (e.g., “same vibe but more sci-fi”, “less dark”, “more like #3”).
  - Start from the prior rec_query_spec and apply the new modifier.
  - Update `query_text` with 2–4 discriminative descriptors total to reflect the change (improve retrieval).
  - Adjust fields like `core_genres`, `sub_genres`, `core_tone`, `key_themes`, `providers`, `year_range` as needed.

- new: user pivots to a different vibe/genre/topic (e.g., “actually give me romcoms”).
  - Build a fresh rec_query_spec; do NOT carry prior constraints unless the user repeats them.

- chat: meta/non-rec questions (e.g., “how does this work?”, “why did you recommend X?”).
  - Do not call `recommendation_agent` unless they explicitly ask for new/updated recs.

Principles:
- Prefer the most recent explicit instructions.
- If unsure between NEW vs REFINE, choose REFINE unless the pivot is clear.

---
## rec_query_spec: how to think about the query

The rec_query_spec is the structured representation of what the user is asking for.

It has fields like:

- query_text:
  - A short, natural-language description of what the user wants, optimized for retrieval.
  - IMPORTANT: `query_text` should be a compact retrieval query, not a transcript.
  - Include the key genres, vibes, themes, tone that help find the right movies.
  - MUST exclude meta-instructions (e.g., "on Netflix", "from the last 5 years", "in the 90s"), greetings, or small talk that are not useful for search.
  - Put providers/year_range into structured fields only; do not include them in query_text.
  - Think of this as the text that will be embedded, so prioritize semantic-rich words.

- media_type:
  - "movie".

- core_genres:
  - Canonical genre names to include or prioritize.

- sub_genres:
  - More specific genre descriptors that refine the core genres, such as "psychological thriller", "romantic comedy",  "neo-noir".
  - These can combine genre + flavor (e.g., “psychological”, “dark”, “romantic”), and help differentiate type of story within a broader genre.

- core_tone:
  - A list of tone/vibe adjectives describing how the content should feel emotionally.
  - Focus on emotional and tonal descriptors, not structure or topic.
  - Examples: "satirical", "dark", "bleak", "light-hearted", "cozy", "wholesome", "melancholic", "grim", "uplifting", "offbeat funny".

- key_themes:
  - Requested thematic ideas or subject-matter concerns.
  - Examples: "existential", "identity", "memory", "grief", "coming-of-age", "class satire", "social critique", "politics", "parenthood".

- providers:
  - streaming services providers requested by the users.

- year_range:
  - Optional release-year constraint as [start_year, end_year] (inclusive).
  - The current year is {{CURRENT_YEAR}}. Use this as the end_year for "from the past 10 years", "after 2010".
  - If you include year_range, you MUST provide both start_year and end_year. Ensure start_year <= end_year.

---
## Session memory delta (critical, minimal)

On EVERY turn, you MUST also produce a small JSON object called `memory_delta` that helps the backend maintain session memory.

Keep `memory_delta` MINIMAL. Do NOT restate the whole rec_query_spec here.

Schema:

{
  "turn_kind": "new" | "refine" | "chat",
  "recent_feedback": {
    "liked_slots": ["3"],
    "disliked_slots": [],
    "notes": "want darker + faster pacing"
  } | null
}

Definitions:
- turn_kind:
  - "new": user is asking for a fresh set of recommendations.
  - "refine": user is iterating on the current request or the last slate.
  - "chat": user is not asking for recommendations.
- recent_feedback:
  - ONLY include this when the user is reacting to prior recommendations or iterating relative to the last slate (e.g., “more like #3”, “too slow”, “something lighter”, “I want something darker” after a previous list).
  - For refinements without slot references (e.g., “darker”), set liked_slots/disliked_slots to empty lists and put the change in notes.
  - Otherwise set it to null.

---
## Opening summary (for fast UI)

On turns where you CALL `recommendation_agent`, you MUST also produce a short string field called `opening_summary`.

Requirements:
- EXACTLY 2 sentences. Max ~220 characters total.
- Must be derived from the FINAL `rec_query_spec` you are sending.
- Contextualize the overall the theme and the overall viewing experience and constraints to the user.
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "recommendation_agent",
            "description": (
                "Run the Reelix recommendation_agent for the current user using a rec_query_spec. "
                "Use this to retrieve, rank, and curate recommendations based on the user's request."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "rec_query_spec": {
                        "type": "object",
                        "description": (
                            "Structured rec_query_spec describing the recommendation query: "
                            "intent, media type, core genres, sub-genres, tone, and structural/thematic preferences."
                        ),
                        "properties": {
                            "query_text": {
                                "type": "string",
                                "description": (
                                    "Compact retrieval-oriented description of what the user wants. "
                                    "Include genre/vibe/tone/structure. Exclude greetings and meta-instructions."
                                ),
                            },
                            "media_type": {
                                "type": "string",
                                "description": "Type of media to recommend. Use 'movie'",
                                "enum": ["movie"],
                            },
                            "core_genres": {
                                "type": "array",
                                "description": (
                                    "List of canonical genre names to prioritize/include "
                                    "(e.g., 'Drama', 'Comedy', 'Science Fiction')."
                                ),
                                "items": {
                                    "type": "string",
                                    "enum": [
                                        "Action",
                                        "Comedy",
                                        "Drama",
                                        "Romance",
                                        "Science Fiction",
                                        "Thriller",
                                        "Adventure",
                                        "Animation",
                                        "Crime",
                                        "Documentary",
                                        "Family",
                                        "Fantasy",
                                        "History",
                                        "Horror",
                                        "Music",
                                        "Mystery",
                                        "War",
                                        "Western",
                                    ],
                                },
                            },
                            "sub_genres": {
                                "type": "array",
                                "description": (
                                    "List of more specific sub-genre descriptors such as "
                                    "'psychological thriller', 'romantic comedy', 'neo-noir', 'dark fantasy'."
                                ),
                                "items": {"type": "string"},
                            },
                            "core_tone": {
                                "type": "array",
                                "description": (
                                    "List of tone/vibe adjectives for how the content should feel emotionally, "
                                    "such as 'satirical', 'cozy', 'bleak', 'uplifting'."
                                ),
                                "items": {"type": "string"},
                            },
                            "narrative_shape": {
                                "type": "array",
                                "description": (
                                    "List of requested narrative or structural properties, such as "
                                    "'plot twists', 'slow-burn', 'nonlinear', 'fast-paced'."
                                ),
                                "items": {"type": "string"},
                            },
                            "key_themes": {
                                "type": "array",
                                "description": (
                                    "List of thematic ideas or subject-matter concerns, such as "
                                    "'existential', 'class satire', 'coming-of-age', 'identity'."
                                ),
                                "items": {"type": "string"},
                            },
                            "providers": {
                                "type": "array",
                                "description": (
                                    "Optional list of streaming providers to include. "
                                ),
                                "items": {
                                    "type": "string",
                                    "enum": [
                                        "Netflix",
                                        "Hulu",
                                        "HBO Max",
                                        "Disney+",
                                        "Apple TV+",
                                        "Amazon Prime Video",
                                        "Paramount+",
                                        "Peacock Premium",
                                        "MGM+",
                                        "Starz",
                                        "AMC+",
                                        "Crunchyroll",
                                        "BritBox",
                                        "Acorn TV",
                                        "Criterion Channel",
                                        "Tubi TV",
                                        "Pluto TV",
                                        "The Roku Channel",
                                    ],
                                },
                            },
                            "year_range": {
                                "description": "Optional release-year range as [start_year, end_year] (inclusive). If the user does not specify a year range, set to null.",
                                "anyOf": [
                                    {
                                        "type": "array",
                                        "items": {
                                            "type": "integer",
                                            "minimum": 1970,
                                            "maximum": 2100,
                                        },
                                        "minItems": 2,
                                        "maxItems": 2,
                                    },
                                    {"type": "null"},
                                ],
                                "default": None,
                            },
                        },
                        "required": ["query_text"],
                        "additionalProperties": False,
                    },
                    "memory_delta": {
                        "type": "object",
                        "description": "Minimal session memory delta for this turn.",
                        "properties": {
                            "turn_kind": {
                                "type": "string",
                                "enum": ["new", "refine", "chat"],
                            },
                            "recent_feedback": {
                                "type": ["object", "null"],
                                "description": (
                                    "Only include when user is reacting to prior recommendations "
                                    "or iterating on the last slate. Otherwise null."
                                ),
                                "properties": {
                                    "liked_slots": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "disliked_slots": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "notes": {"type": "string"},
                                },
                                "required": ["liked_slots", "disliked_slots", "notes"],
                                "additionalProperties": False,
                            },
                        },
                        "required": ["turn_kind", "recent_feedback"],
                        "additionalProperties": False,
                    },
                    "opening_summary": {
                        "type": "string",
                        "description": (
                            "Exactly 2 sentences (max ~220 chars). "
                            "Summarize the user's current request based on rec_query_spec. "
                            "Do NOT name specific titles. Do NOT promise outcomes."
                        ),
                    },
                },
                "required": ["rec_query_spec", "memory_delta", "opening_summary"],
                "additionalProperties": False,
            },
        },
    },
]


def build_orchestrator_user_prompt(agent_input: InteractiveAgentInput) -> str:
    """
    Normalize the agent input into a single user message string that includes both free-text query and structured filters.
    """
    parts: list[str] = []

    if agent_input.query_text:
        parts.append(f"User query: {agent_input.query_text}")

    if agent_input.media_type:
        parts.append(f"Media type: {agent_input.media_type.value}")

    # if agent_input.query_filters:
    #     parts.append("Structured filters (JSON):")
    #     # you can safely stringify; model will still parse it fine

    #     filters = (
    #         agent_input.query_filters.model_dump()
    #         if hasattr(agent_input.query_filters, "model_dump")
    #         else agent_input.query_filters
    #     )
    #     parts.append(json.dumps(filters, ensure_ascii=False))

    # Fallback if nothing was set
    if not parts:
        parts.append("User is asking for personalized recommendations.")

    return "\n\n".join(parts)


def build_session_memory_message(
    session_memory: dict[str, Any] | None,
) -> tuple[str | None, RecQuerySpec | None, dict[str, Any] | None]:
    """
    Convert raw session memory into a small system message for the LLM.
    """
    if not isinstance(session_memory, dict) or not session_memory:
        return None, None, None

    summary = session_memory.get("summary") or {}
    last_spec_raw = session_memory.get("last_spec")
    slot_map = session_memory.get("slot_map") or None

    # Parse last_spec into RecQuerySpec for optional debug/telemetry
    prior_spec = None
    if isinstance(last_spec_raw, dict):
        try:
            prior_spec = RecQuerySpec(**last_spec_raw)
        except Exception:
            prior_spec = None

    # Format slot_map compactly to reduce tokens
    slot_lines: list[str] = []
    if isinstance(slot_map, dict):
        for k in sorted(
            slot_map.keys(), key=lambda x: int(x) if str(x).isdigit() else 999
        ):
            item = slot_map.get(k) or {}
            title = item.get("title") or "?"
            yr = item.get("release_year")
            slot_lines.append(f"#{k}: {title}" + (f" ({yr})" if yr else ""))

    # Only include the minimal summary keys that matter for next turn
    summary_compact = {}
    if isinstance(summary, dict):
        if "turn_kind" in summary:
            summary_compact["turn_kind"] = summary.get("turn_kind")
        if "recent_feedback" in summary:
            summary_compact["recent_feedback"] = summary.get("recent_feedback")
        if "last_user_message" in summary:
            summary_compact["last_user_message"] = summary.get("last_user_message")
        if "last_user_message" in summary:
            summary_compact["last_admin_message"] = summary.get("last_admin_message")

    msg_parts: list[str] = [
        "SESSION MEMORY (server-provided; do NOT reveal to the user).",
        "Use this to interpret short follow-ups (e.g., 'darker') and references (e.g., '#3').",
    ]

    if summary:
        msg_parts.append(
            "summary (JSON): " + json.dumps(summary_compact, ensure_ascii=False)
        )

    # Include last_spec for refinements. Keep it compact.
    if isinstance(last_spec_raw, dict):
        msg_parts.append(
            "last_spec (JSON): " + json.dumps(last_spec_raw, ensure_ascii=False)
        )

    if slot_lines:
        msg_parts.append("last slate slot_map:")
        msg_parts.extend(slot_lines)

    # Guidance to avoid over-carry
    msg_parts.append(
        "Interpretation rules: "
        "If the user is refining, start from last_spec and patch it. "
        "If the user is starting a new request, ignore last_spec/slot_map unless they explicitly say to keep something."
    )

    return "\n".join(msg_parts), prior_spec, slot_map
