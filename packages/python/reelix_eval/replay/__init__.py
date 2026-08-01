"""Stage-scoped replay — the verification engine.

Freeze real queries and their retrieved candidates into an eval set, then re-run
only the curator stage against the working tree. Frozen candidates mean a replay
needs no Qdrant and no models; the curator LLM is the only source of variance,
which is exactly what a prompt change is meant to move.

Only the curator stage is replayable in this pass — retrieval-level findings
(weights, recipes, cross-encoder) stay unverified proposals.
"""

from reelix_eval.replay.curator import CaseReplay, ReplayRun, replay, replay_case
from reelix_eval.replay.evalset import (
    EVALSET_VERSION,
    EvalCase,
    FrozenCandidate,
    evalset_path,
    load,
    snapshot,
)

__all__ = [
    "EVALSET_VERSION",
    "CaseReplay",
    "EvalCase",
    "FrozenCandidate",
    "ReplayRun",
    "evalset_path",
    "load",
    "replay",
    "replay_case",
    "snapshot",
]