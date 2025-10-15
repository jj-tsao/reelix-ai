from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Tuple

from reelix_core.types import UserTasteContext
from reelix_ranking.types import Candidate, FeatureContribution, ScoreBreakdown


@dataclass(frozen=True)
class NormAnchors:
    rating_floor: float
    rating_ceil: float
    pop_anchor: float  # used with log1p


# Module-level defaults
DEFAULT_ANCHORS: Dict[str, NormAnchors] = {
    "movie": NormAnchors(
        rating_floor=6.0, rating_ceil=9.0, pop_anchor=31.0
    ),  # pop_anchor = ~P99(27)*1.15
    "tv": NormAnchors(
        rating_floor=7.0, rating_ceil=9.0, pop_anchor=58.0
    ),  # pop_anchor = ~P99(50)*1.15
}


def set_metadata_anchors(media_type: str, anchors: NormAnchors) -> None:
    """Runtime override (feature flag, admin panel, tests)."""
    DEFAULT_ANCHORS[media_type.lower()] = anchors


def _clamp01(x: float) -> float:
    return 0.0 if x <= 0.0 else 1.0 if x >= 1.0 else x


def bayes_quality(avg, cnt, mu=7.0, m=2000):
    avg = float(avg or 0.0)
    cnt = float(cnt or 0.0)
    return (mu * m + avg * cnt) / (m + cnt)


def norm_rating(x: float | None, floor_: float, ceil_: float) -> float:
    if x is None:
        return 0.0
    return _clamp01((float(x) - floor_) / max(1e-6, (ceil_ - floor_)))


def norm_popularity(pop, anchor: float, alpha: float = 0.6) -> float:
    if pop is None:
        return 0.0
    return (math.log1p(pop) / math.log1p(anchor)) ** alpha


def genre_boost(user_genres: set[str], item_genres: set[str]) -> float:
    if not user_genres or not item_genres:
        return 0.0

    inter = len(user_genres & item_genres)
    total_user_pref = len(user_genres)

    # Only rewards matches, no punish to non-overlapping genres since user_genres are cold start interests in first_rec
    return inter / total_user_pref


def metadata_rerank(
    *,
    candidates: List[Candidate],
    media_type: str,
    user_context: UserTasteContext | None = None,
    weights: Dict[str, float] = dict(
        dense=0.60, sparse=0.10, rating=0.20, popularity=0.10, genre=0
    ),
    anchors: NormAnchors | None = None,
) -> List[Tuple[Candidate, float, ScoreBreakdown]]:
    mt = media_type.lower()
    a = anchors or DEFAULT_ANCHORS.get(mt, DEFAULT_ANCHORS["movie"])

    s_vals = sorted(
        [
            float(c.sparse_score)
            for c in candidates
            if c.sparse_score and c.sparse_score > 0.0
        ]
    )
    p95 = s_vals[int(0.95 * (len(s_vals) - 1))] if s_vals else 1e-6
    den = math.log1p(p95)
    user_genres = user_context.signals.genres_include if user_context else []

    out: List[Tuple[Candidate, float, ScoreBreakdown]] = []
    for c in candidates:
        dense = float(c.dense_score or 0.0)
        raw_s = float(c.sparse_score or 0.0)
        sparse = _clamp01(math.log1p(max(0.0, raw_s)) / max(1e-6, den))
        raw_r = bayes_quality(
            (c.payload or {}).get("vote_average"), (c.payload or {}).get("vote_count")
        )
        q = norm_rating(raw_r, a.rating_floor, a.rating_ceil)
        p = norm_popularity((c.payload or {}).get("popularity"), a.pop_anchor)
        c_genres = (c.payload or {}).get("genres")
        g = (
            genre_boost(set(user_genres), set(c_genres))
            if c_genres and user_genres
            else 0
        )
        
        feats: Dict[str, FeatureContribution] = {
            "dense": FeatureContribution(
                feature="dense",
                value=dense,
                weight=float(weights.get("dense", 0.0)),
                contribution=float(weights.get("dense", 0.0)) * dense,
            ),
            "sparse": FeatureContribution(
                feature="sparse",
                value=sparse,
                weight=float(weights.get("sparse", 0.0)),
                contribution=float(weights.get("sparse", 0.0)) * sparse,
            ),
            "rating": FeatureContribution(
                feature="rating",
                value=q,
                weight=float(weights.get("rating", 0.0)),
                contribution=float(weights.get("rating", 0.0)) * q,
            ),
            "popularity": FeatureContribution(
                feature="popularity",
                value=p,
                weight=float(weights.get("popularity", 0.0)),
                contribution=float(weights.get("popularity", 0.0)) * p,
            ),
            "genre": FeatureContribution(
                feature="genre",
                value=g,
                weight=float(weights.get("genre", 0.0)),
                contribution=float(weights.get("genre", 0.0)) * g,
            ),
        }

        breakdown = ScoreBreakdown(features=feats)
        score = breakdown.total

        out.append((c, score, breakdown))

    out.sort(key=lambda t: t[1], reverse=True)

    return out
