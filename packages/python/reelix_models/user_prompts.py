from __future__ import annotations
from typing import Iterable, Mapping, List, Optional
import re
from reelix_ranking.types import Candidate
from reelix_core.types import UserSignals


DEFAULT_LIMITS = dict(
    genres=7,
    keywords=12,
    liked=7,
    disliked=5,
)


# == User prompt builder for for-you feed discovery mode ==


def build_for_you_user_prompt(
    *,
    candidates: List[Candidate],
    user_signals: UserSignals,
    query_text: Optional[str] = None,
    limits: Mapping[str, int] = DEFAULT_LIMITS,
    can_per_call: int = 6,
) -> str:
    """
    Build the User Prompt for the discover/for-you/why LLM call.

    Args:
        candidates: Ordered list of Candidate items.
        user_genres: Iterable of user-selected genres (already ranked/weighted upstream).
        user_keywords: Iterable of user-selected keywords/vibes (already ranked/weighted upstream).
        liked_titles: Iterable of positively-rated titles (recent/highest-weight first).
        disliked_titles: Iterable of negatively-rated titles (strongest negatives first).
        query_text: Optional short session theme (≤ ~12 words). If None, note as “no explicit request”.
        limits: Caps for genres/keywords/liked/disliked. Defaults match recommended ranges.

    Returns:
        Markdown string for the User Prompt to send to LLM.
    """

    # helpers
    def _dedupe_keep_order(items: Iterable[str]) -> list[str]:
        seen = set()
        out = []
        for x in items:
            x = (x or "").strip()
            if x and x.lower() not in seen:
                seen.add(x.lower())
                out.append(x)
        return out

    def _cap(items: Iterable[str], k: int) -> list[str]:
        out = list(items)
        return out[: max(0, int(k))]

    def _csv(items: Iterable[str]) -> str:
        xs = [x.strip() for x in items if x and x.strip()]
        return ", ".join(xs) if xs else "(none)"

    def _sanitize_code_block(block: str) -> str:
        # Replace any standalone ``` with indented fence
        return re.sub(r"```", "``\u200b`", block or "")

    # context attributes
    pos_titles = [i.title for i in user_signals.loved_titles()]
    if len(pos_titles) < 7:
        pos_titles.extend([i.title for i in user_signals.liked_titles()])
    neg_titles = [i.title for i in user_signals.disliked_titles()]

    # apply dedupe + caps
    genres = _cap(
        _dedupe_keep_order(user_signals.genres_include), limits.get("genres", 7)
    )
    keywords = _cap(
        _dedupe_keep_order(user_signals.keywords_include), limits.get("keywords", 12)
    )
    liked = _cap(_dedupe_keep_order(pos_titles), limits.get("liked", 7))
    disliked = _cap(
        _dedupe_keep_order(neg_titles),
        limits.get("disliked", 5),
    )

    parts: list[str] = []

    # header
    if query_text and query_text.strip():
        parts.append(
            "Here is the user’s request and taste signals, followed by the exact candidates to use.\n"
        )
        parts.append("**User Query:**")
        parts.append(query_text.strip() + "\n")
    else:
        parts.append(
            "Here is the user’s taste signals, followed by the exact candidates to use.\n"
        )

    # user signals
    parts.append("**User Signals:**")
    parts.append(f"- Selected Genres: {_csv(genres)}")
    parts.append(f"- Selected Keywords: {_csv(keywords)}")
    parts.append(f"- Liked Titles: {_csv(liked)} ")
    parts.append(f"- Disliked Titles: {_csv(disliked) or 'None'}")
    parts.append("")

    # candidates
    parts.append("**Candidates (use all, in this order):**")
    parts.append(
        "Each block below contains the full context for one title. Do not combine fields across titles.\n"
    )

    for idx, c in enumerate(candidates[:can_per_call], start=1):
        media_id = f"Media ID: {(c.payload.get('media_id', ''))}"
        ctx = _sanitize_code_block(str(c.payload.get("embedding_text", "")).strip())
        # Guardrail: empty context → still emit fenced empty block to preserve count/order
        parts.append("```")
        parts.append(media_id)
        parts.append(ctx)
        parts.append("```")
        # (No extra blank line; streaming parsers often prefer tight blocks)

    # explicit instructions (verbatim from template expectations)
    parts.append("\n**Instructions:**")
    parts.append("- Output six recommendation blocks using the specified format.")
    parts.append("- After each block, append <!-- END_MOVIE -->.")

    return "\n".join(parts)


# == User prompt builder for interactive recommendation mode ==


def format_rec_context(candidates: list):
    context = "\n\n".join([c.payload.get("llm_context", "") for c in candidates])
    return context


def build_interactive_user_prompt(
    *, candidates: list, query_text: str, user_signals: UserSignals | None = None
):
    context = format_rec_context(candidates=candidates)
    user_message = f"Here is the user query: {query_text}\n\nHere are the candidate items:\n{context}"
    return user_message
