"""Deterministic spec-violation check.

Recomputes `spec_violation` in code from `spec_json` + the candidate's Qdrant
payload. Where this disagrees with the judge's own answer we have a free,
continuous calibration signal on the judge — a rising disagreement rate means the
judge is drifting, independent of any change to the system under test.

Only HARD constraints are checkable: excluded genres, `year_range`, and
`providers`. Tone and themes are judgement calls and are never counted here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SpecViolation:
    violated: bool
    reasons: list[str]


def _norm(s: str) -> str:
    return str(s).strip().casefold()


def _spec_provider_ids(names: list[str]) -> set[int]:
    """Spec provider NAMES → TMDB provider IDs.

    Qdrant payloads store `watch_providers` as TMDB integer IDs, while the spec
    carries display names ("Netflix"). Comparing the two directly matches nothing
    and would flag a violation on every candidate whenever providers are set.
    Reuses the retrieval layer's own mapping so this check can't drift from the
    filter that actually ran.
    """
    try:
        from reelix_retrieval.qdrant_filter import provider_ids_from_names
    except ImportError:
        logger.warning("qdrant_filter unavailable — skipping provider check")
        return set()

    return set(provider_ids_from_names(names, on_unknown="drop"))


def check_spec_violation(spec: dict | None, candidate) -> SpecViolation:
    """Check one candidate against the hard constraints in `spec`.

    `candidate` is anything exposing `genres`, `release_year`, `watch_providers`
    (a `store.CandidateDetail` or an evalset payload wrapper).

    Returns `violated=False` when the spec sets no hard constraints, or when the
    candidate's payload lacks the field needed to judge one — absence of evidence
    is not a violation, and treating it as one would make every un-backfilled
    candidate look broken.
    """
    reasons: list[str] = []
    if not spec:
        return SpecViolation(False, reasons)

    genres = {_norm(g) for g in (getattr(candidate, "genres", None) or [])}
    year = getattr(candidate, "release_year", None)

    # Payload providers are TMDB integer IDs.
    provider_ids: set[int] = set()
    for p in getattr(candidate, "watch_providers", None) or []:
        try:
            provider_ids.add(int(p))
        except (TypeError, ValueError):
            continue

    excluded = {_norm(g) for g in (spec.get("exclude_genres") or [])}
    if excluded and genres:
        hits = sorted(excluded & genres)
        if hits:
            reasons.append(f"excluded genre: {', '.join(hits)}")

    year_range = spec.get("year_range")
    if year_range and year is not None:
        try:
            lo, hi = int(year_range[0]), int(year_range[1])
            if not (lo <= int(year) <= hi):
                reasons.append(f"year {year} outside {lo}-{hi}")
        except (TypeError, ValueError, IndexError):
            pass

    wanted = _spec_provider_ids(spec.get("providers") or [])
    if wanted and provider_ids and not (wanted & provider_ids):
        reasons.append("not on any requested provider")

    return SpecViolation(bool(reasons), reasons)