from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Optional, Dict
from qdrant_client.models import ExtendedPointId


@dataclass
class Candidate:
    id: ExtendedPointId
    payload: dict[str, Any]
    dense_score: Optional[float] = None
    sparse_score: Optional[float] = None


@dataclass
class ScoreTrace:
    id: str
    # Stage ranks (lower is better)
    dense_rank: int | None = None
    sparse_rank: int | None = None
    # Scalar / model scores
    meta_score: float | None = None
    meta_contribution: FeatureContribution | None = None
    ce_score: float | None = None
    final_rrf: float | None = None


@dataclass(frozen=True)
class FeatureContribution:
    feature: str                 # "dense", "sparse", "rating", "popularity", "genre"
    value: float                 # feature value (pre-weight, posr-normalization)
    weight: float                # weight used in this run
    contribution: float          # weight * value

@dataclass(frozen=True)
class ScoreBreakdown:
    features: Dict[str, FeatureContribution]  # keyed by feature name

    @property
    def total(self) -> float:
        return sum(fc.contribution for fc in self.features.values())

