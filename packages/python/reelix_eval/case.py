"""Small versioned incident record. Checkpoints support inspection, not restart/resume.

Each event carries a canonical JSON payload so later mutations cannot rewrite
history. Files are exclusive, append-only snapshots; no crash durability claim.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Literal

from reelix_eval.trust import Evidence, Policy, TrustedContext, digest

Stage = Literal['created', 'investigation', 'assurance', 'revision', 'proposal', 'policy', 'publication', 'finished']
Status = Literal['active', 'completed', 'provisional', 'blocked', 'failed']
TRANSITIONS = {
    'created': {'investigation', 'publication'},
    'investigation': {'assurance', 'publication'},
    'assurance': {'revision', 'proposal', 'publication'},
    'revision': {'assurance', 'publication'},
    'proposal': {'policy', 'publication'},
    'policy': {'publication'},
    'publication': {'finished'},
    'finished': set(),
}


@dataclass(frozen=True)
class CaseIdentity:
    case_id: str
    mandate: str
    window: str
    query_ids: tuple[str, ...]
    source_revision: str
    policy_revision: str
    source_commit: str = 'unknown'
    permitted_sources: tuple[str, ...] = ('packages/python',)
    capabilities: tuple[str, ...] = ('telemetry_read', 'source_read', 'propose')

    def __post_init__(self):
        if (not self.case_id or self.case_id in ('.', '..')
                or any(c in self.case_id for c in ('/', '\\', '\x00'))):
            raise ValueError('case_id must be a directory name')
        if not self.mandate.strip() or not self.window.strip():
            raise ValueError('case mandate and window required')


@dataclass(frozen=True)
class CaseEvent:
    sequence: int
    at: str
    kind: str
    origin: str
    binding: str
    payload_json: str


@dataclass
class InvestigationCase:
    identity: CaseIdentity
    storage: Path
    schema_version: int = field(default=1, init=False)
    stage: Stage = field(default='created', init=False)
    status: Status = field(default='active', init=False)
    assessment_ref: str | None = field(default=None, init=False)
    proposal_ref: str | None = field(default=None, init=False)
    obligations: tuple[str, ...] = field(default=(), init=False)
    _history: list[CaseEvent] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self):
        # Refuse accidental reuse. Restart inspection is supported; replaying an
        # interrupted stage with persisted authority is deliberately unsupported.
        self.storage = self.storage / self.identity.case_id
        self.storage.mkdir(parents=True, exist_ok=False)
        self.record('initialized', asdict(self.identity))

    @property
    def history(self) -> tuple[CaseEvent, ...]:
        return tuple(self._history)

    def binding(self, ctx: TrustedContext, policy: Policy) -> str:
        if ctx.case_id != self.identity.case_id:
            raise ValueError('cross-case trusted context')
        return digest([asdict(self.identity), ctx.evidence.snapshot,
                       ctx.current_revision, policy.revision, self.assessment_ref, self.proposal_ref])

    def record(self, kind: str, payload: dict, *, origin='host', binding='') -> CaseEvent:
        event = CaseEvent(len(self._history), datetime.now(timezone.utc).isoformat(),
                          kind, origin, binding, json.dumps(payload, sort_keys=True, allow_nan=False))
        self._history.append(event)
        path = self.storage / f'{event.sequence:04d}.json'
        with path.open('x', encoding='utf-8') as stream:
            json.dump(self.to_dict(), stream, indent=2, allow_nan=False)
        return event

    def transition(self, target: Stage, reason: str):
        if target not in TRANSITIONS[self.stage]:
            raise ValueError(f'invalid transition {self.stage} -> {target}')
        previous = self.stage
        self.stage = target
        self.record('transition', {'from': previous, 'to': target, 'reason': reason})

    def register(self, evidence: Evidence):
        if any(e.kind == 'evidence_registered' and json.loads(e.payload_json)['evidence_id'] == evidence.evidence_id for e in self._history):
            return
        if evidence.case_id != self.identity.case_id:
            raise ValueError('cross-case evidence')
        if evidence.kind == 'runtime' and (not evidence.query_ids or not set(evidence.query_ids) <= set(self.identity.query_ids)):
            raise ValueError('out-of-scope runtime observation')
        self.record('evidence_registered', asdict(evidence))

    def to_dict(self):
        return {'schema_version': self.schema_version, 'identity': asdict(self.identity),
                'stage': self.stage, 'status': self.status, 'assessment_ref': self.assessment_ref,
                'proposal_ref': self.proposal_ref, 'obligations': self.obligations,
                'history': [asdict(e) for e in self._history]}

    @staticmethod
    def inspect(path: Path) -> dict:
        """Read an existing checkpoint without restoring execution authority."""
        data = json.loads(path.read_text())
        if data['schema_version'] != 1:
            raise ValueError('unsupported case schema')
        return data
