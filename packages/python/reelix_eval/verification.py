"""Small execution-derived verification contract, not remediation authorization.

Receipts are created by the host replay/scoring paths, never deserialized from agent
arguments. A receipt attests only the recorded revision/cases/policy, not the
truth of a diagnosis or the causal correctness of a proposed narrative diff.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import math


@dataclass(frozen=True)
class AcceptancePolicy:
    min_cases: int = 20
    min_gain: float = 0.3
    required_controls: int = 2

    def __post_init__(self):
        if type(self.min_cases) is not int or self.min_cases < 2:
            raise ValueError("policy.min_cases must be at least two")
        if not math.isfinite(self.min_gain) or self.min_gain < 0.3:
            raise ValueError("policy.min_gain must respect the 0.3 minimum noise margin")
        if type(self.required_controls) is not int or self.required_controls < 2:
            raise ValueError("policy requires at least two unchanged controls")


@dataclass(frozen=True)
class RevisionEvidence:
    expected: str
    loaded: str
    files: tuple[tuple[str, str], ...]
    imported_files: tuple[tuple[str, str], ...]
    prompt_sha256: str
    origins_valid: bool
    worker_pid: int
    execution_id: str = ""
    expected_prompt_sha256: str = ""
    loaded_bindings: tuple[tuple[str, str], ...] = ()

    @property
    def matched(self) -> bool:
        digest = hashlib.sha256(json.dumps(dict(self.files), sort_keys=True).encode()).hexdigest()
        return (type(self.origins_valid) is bool and self.origins_valid and bool(self.imported_files) and bool(self.loaded_bindings)
                and bool(self.prompt_sha256) and self.prompt_sha256 == self.expected_prompt_sha256
                and self.expected == self.loaded == digest and type(self.worker_pid) is int
                and self.worker_pid > 0 and bool(self.execution_id)
                and all(dict(self.files).get(p) == sha for p, sha in self.imported_files))


@dataclass(frozen=True)
class VerificationReceipt:
    evalset_sha256: str
    case_ids: tuple[str, ...]
    failed_case_ids: tuple[str, ...]
    candidate: RevisionEvidence | None
    baseline: RevisionEvidence | None = None
    attempted: bool = True
    execution_completed: bool = False
    outputs_valid: bool = False
    evaluation_valid: bool = False
    controls: tuple[RevisionEvidence | None, ...] = ()
    # axis, baseline value, candidate value, unchanged-control spread
    axes: tuple[tuple[str, float, float, float], ...] = ()
    policy: AcceptancePolicy = field(default_factory=AcceptancePolicy)
    issues: tuple[str, ...] = ()
    evaluation_sha256: str = ""
    judge_model: str = ""
    evaluated_case_ids: tuple[str, ...] = ()
    evaluation_failed_case_ids: tuple[str, ...] = ()

    def __post_init__(self):
        for name in ('attempted','execution_completed','outputs_valid','evaluation_valid'):
            if type(getattr(self,name)) is not bool:
                raise ValueError(f'verification.{name}: expected boolean')
        for name in ('case_ids','failed_case_ids','evaluated_case_ids','evaluation_failed_case_ids','issues'):
            value=getattr(self,name)
            if not isinstance(value,tuple) or any(not isinstance(x,str) or not x for x in value):
                raise ValueError(f'verification.{name}: expected tuple of nonempty strings')
        if not self.attempted and (self.execution_completed or self.outputs_valid or self.evaluation_valid
                                   or self.candidate is not None or self.axes):
            raise ValueError('verification.not_attempted: inconsistent execution evidence')

    @property
    def revision_matched(self) -> bool:
        return (self.candidate is not None and self.baseline is not None
                and self.candidate.matched and self.baseline.matched
                and all(c is not None and c.matched and c.loaded == self.baseline.loaded for c in self.controls))

    @property
    def criteria_satisfied(self) -> bool:
        required = {"avg_relevance", "avg_novelty", "avg_spec_fidelity",
                    "avg_list_coherence", "spec_violation_rate_judge"}
        if (not self.attempted or not self.execution_completed or not self.revision_matched
                or not self.outputs_valid or not self.evaluation_valid or self.failed_case_ids
                or self.issues or self.evaluation_failed_case_ids
                or len(self.evaluated_case_ids) != len(self.case_ids)
                or set(self.evaluated_case_ids) != set(self.case_ids)
                or not self.evalset_sha256 or not self.evaluation_sha256 or not self.judge_model
                or len(self.case_ids) != len(set(self.case_ids))
                or len(self.case_ids) < self.policy.min_cases
                or len(self.controls) < self.policy.required_controls
                or len({c.execution_id for c in self.controls}) != len(self.controls)
                or (self.baseline and self.baseline.execution_id in {c.execution_id for c in self.controls})
                or self.candidate.execution_id in {self.baseline.execution_id, *(c.execution_id for c in self.controls)}
                or {a[0] for a in self.axes} != required or len(self.axes) != len(required)
                or self.candidate.loaded == self.baseline.loaded):
            return False
        gain = False
        for name, base, candidate, noise in self.axes:
            if not all(type(v) in (int, float) and math.isfinite(v) for v in (base, candidate, noise)) or noise < 0:
                return False
            upper = 1 if name == "spec_violation_rate_judge" else 5
            lower = 0 if upper == 1 else 1
            if not lower <= base <= upper or not lower <= candidate <= upper:
                return False
            delta = base - candidate if name == "spec_violation_rate_judge" else candidate - base
            if delta < 0:
                return False  # No axis may regress to obtain a successful receipt.
            if name != "spec_violation_rate_judge" and delta > max(self.policy.min_gain, noise):
                gain = True
        return gain

    @property
    def verified(self) -> bool | None:
        return self.criteria_satisfied if self.attempted else None

    @property
    def decision(self) -> str:
        if not self.attempted: return "not_attempted"
        if not self.execution_completed: return "execution_failed"
        if not self.revision_matched: return "revision_unverified"
        if not self.outputs_valid: return "incomplete_outputs"
        if not self.evaluation_valid: return "invalid_evaluation"
        if self.criteria_satisfied: return "improved"
        return "criteria_not_satisfied"

    def to_dict(self) -> dict:
        return {**asdict(self), "revision_matched": self.revision_matched,
                "candidate_revision_matched": bool(self.candidate and self.candidate.matched),
                "baseline_revision_matched": bool(self.baseline and self.baseline.matched),
                "criteria_satisfied": self.criteria_satisfied,
                "verified": self.verified, "decision": self.decision}

    @property
    def receipt_id(self) -> str:
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode()).hexdigest()
