from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping, Optional
from qdrant_client.models import ExtendedPointId


@dataclass
class Candidate:
    id: ExtendedPointId
    payload: Optional[Mapping[str, Any]]
    dense_score: Optional[float] = None
    sparse_score: Optional[float] = None


@dataclass
class ScoreTrace:
    id: str
    # Stage ranks (lower is better)
    dense_rank: Optional[int] = None
    sparse_rank: Optional[int] = None
    # Scalar / model scores
    meta_score: Optional[float] = None
    ce_score: Optional[float] = None
    final_rrf: Optional[float] = None
