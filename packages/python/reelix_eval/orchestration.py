"""Application-owned stage progression. Agent outputs never convey authority."""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import time
from typing import Any, Protocol

from reelix_eval.case import InvestigationCase
from reelix_eval.report import Report, ReportValidationError, finding_from_dict, parse_json_field, write
from reelix_eval.trust import (
    Input, InvestigationAssessment, RemediationProposal, Text, Policy, PolicyDecision,
    TrustedContext, _in_scope, decision_is_current, digest, evaluate,
)


class AssessmentSubmission(Input):
    case_id: Text
    policy_revision: Text
    source_revision: Text
    assessment: InvestigationAssessment
    finding: dict[str, Any] | None = None


class ProposalSubmission(Input):
    case_id: Text
    policy_revision: Text
    source_revision: Text
    assessment_sha256: Text
    proposal: RemediationProposal | None
    no_action_reason: Text = ''


@dataclass(frozen=True)
class StageRequest:
    stage: str
    case_id: str
    input_json: str
    max_turns: int
    timeout_seconds: float
    output_type: type[Input]


class StageExecutor(Protocol):
    async def __call__(self, request: StageRequest) -> Any: ...


class HostOrchestrator:
    def __init__(self, case: InvestigationCase, ctx: TrustedContext, executor: StageExecutor,
                 reports_dir: Path, *, policy=Policy(), max_turns=30, timeout_seconds=300., evaluator=evaluate):
        if max_turns < 1 or timeout_seconds <= 0:
            raise ValueError('stage budgets must be positive')
        if (case.identity.case_id != ctx.case_id or case.identity.source_revision != ctx.current_revision
                or case.identity.policy_revision != policy.revision
                or case.identity.query_ids != ctx.query_ids):
            raise ValueError('case identity does not match trusted context')
        self.case, self.ctx, self.executor = case, ctx, executor
        self.reports_dir, self.policy = reports_dir, policy
        self.max_turns, self.timeout_seconds, self.evaluator = max_turns, timeout_seconds, evaluator
        self.assessment = None
        self.finding = None
        self.proposal = None
        self.decisions: list[PolicyDecision] = []
        self.seen_evidence: set[str] = set()

    def _sync_evidence(self):
        for key, record in sorted(self.ctx.evidence._records.items()):
            if key not in self.seen_evidence:
                self.case.register(record)
                self.seen_evidence.add(key)

    async def _stage(self, stage, output_type, feedback=()):
        self.case.transition(stage, 'host starts bounded reasoning stage')
        payload = {'case': {k: v for k, v in self.case.to_dict().items() if k != 'history'}, 'policy': asdict(self.policy),
                   'assessment': self.assessment.model_dump(mode='json') if self.assessment else None,
                   'feedback': list(feedback), 'source_revision': self.ctx.current_revision,
                   'evidence': [asdict(e) for e in self.ctx.evidence._records.values()],
                   'assessment_sha256': digest(self.assessment) if self.assessment else None}
        request = StageRequest(stage, self.case.identity.case_id, json.dumps(payload), self.max_turns,
                               self.timeout_seconds, output_type)
        self.case.record('stage_input', {'stage': stage, 'input': payload,
                         'max_turns': request.max_turns, 'timeout_seconds': request.timeout_seconds},
                         binding=self.case.binding(self.ctx, self.policy))
        started = time.monotonic()
        try:
            raw = await asyncio.wait_for(self.executor(request), timeout=self.timeout_seconds)
            self._sync_evidence()
            # Preserve output before validation, including rejected attempts to
            # inject decisions. No model-supplied field populates trusted context.
            self.case.record('stage_output', {'stage': stage, 'output': raw}, origin='agent',
                             binding=self.case.binding(self.ctx, self.policy))
            if isinstance(raw, str):
                raw = parse_json_field(raw, 'stage_output', dict)
            parsed = output_type.model_validate_json(json.dumps(raw, allow_nan=False))
            if (parsed.case_id != self.case.identity.case_id or parsed.policy_revision != self.policy.revision
                    or parsed.source_revision != self.ctx.current_revision):
                raise ValueError('stage output has stale or foreign binding')
            return parsed
        finally:
            self.case.record('stage_timing', {'stage': stage, 'elapsed_seconds': time.monotonic() - started})

    def _accept_assessment(self, submission):
        a = submission.assessment
        finding = finding_from_dict(submission.finding) if submission.finding is not None else None
        if a.outcome == 'finding':
            if finding is None or not finding.query_ids or not set(finding.query_ids) <= set(self.ctx.query_ids):
                raise ValueError('finding requires incident query IDs')
            # Verification assertions cannot be supplied by the reasoning stage.
            if finding.verified is not None or finding.verification_id is not None:
                raise ValueError('agent verification assertion rejected')
            expected = digest(asdict(finding))
        else:
            if finding is not None or (a.outcome == 'clean' and (a.causal_hypothesis or a.contradictions or a.missing_evidence)):
                raise ValueError('contradictory no-finding assessment')
            expected = digest({'outcome': a.outcome})
        if a.finding_sha256 != expected:
            raise ValueError('finding content digest mismatch')
        # Unknown evidence is retained as an obligation, never registered from claims.
        # Known evidence from another case/query cannot silently satisfy this finding.
        for claim in a.observations + a.runtime_preconditions:
            e = self.ctx.evidence.resolve(claim.evidence_id)
            if e and (not _in_scope(e, self.ctx) or (finding and not set(e.query_ids) <= set(finding.query_ids))):
                raise ValueError('observation outside finding scope')
        self.ctx.findings = {a.finding_id: expected}
        self.ctx.finding_query_ids = {a.finding_id: tuple(finding.query_ids) if finding else self.ctx.query_ids}
        self.assessment, self.finding = a, finding
        self.case.assessment_ref = digest(a)
        self.case.record('assessment_accepted', submission.model_dump(mode='json'), origin='agent',
                         binding=self.case.binding(self.ctx, self.policy))

    def _assure(self, step):
        self.case.transition('assurance' if step in ('proposal_readiness', 'publication') else 'policy',
                             'mandatory independent assurance')
        decision = self.evaluator(self.assessment, self.proposal, step, self.ctx, self.policy)
        self.decisions.append(decision)
        self.case.obligations = decision.requirements
        self.case.record('assurance', asdict(decision), binding=self.case.binding(self.ctx, self.policy))
        return decision

    def _ready(self, decision):
        return (decision.outcome != 'deny'
                and decision_is_current(decision, self.assessment, self.proposal, self.ctx, self.policy)
                and all(c.status == 'satisfied' for c in decision.evaluation.conditions
                        if c.condition_id in decision.evaluation.required_conditions))

    @staticmethod
    def _feedback(decision):
        required = set(decision.evaluation.required_conditions)
        return tuple({'condition_id': c.condition_id, 'status': c.status,
                      'kind': 'human_judgment' if c.method == 'semantic_requires_review' else 'evidence',
                      'next_action': c.next_action, 'rationale': c.rationale}
                     for c in decision.evaluation.conditions
                     if c.condition_id in required and c.status != 'satisfied')

    def _review_proposal(self, submission, readiness):
        if not decision_is_current(readiness, self.assessment, None, self.ctx, self.policy):
            raise ValueError('proposal readiness became stale during drafting')
        if submission.assessment_sha256 != digest(self.assessment):
            raise ValueError('proposal assessment binding mismatch')
        if submission.proposal is None:
            if not submission.no_action_reason.strip():
                raise ValueError('declining remediation requires an explanation')
            self.case.record('proposal_declined', {'reason': submission.no_action_reason}, origin='agent')
            return 'provisional', 'no appropriate remediation proposed; diagnosis retained'
        if submission.proposal.finding_id != self.assessment.finding_id:
            raise ValueError('proposal finding binding mismatch')
        self.proposal = submission.proposal
        self.case.proposal_ref = digest(self.proposal)
        self.case.record('proposal_accepted', submission.model_dump(mode='json'), origin='agent',
                         binding=self.case.binding(self.ctx, self.policy))
        decision = self._assure('sandbox_candidate')
        status = 'blocked' if decision.outcome == 'deny' else 'completed' if decision.outcome == 'sandbox_candidate' else 'provisional'
        return status, f'policy outcome: {decision.outcome}; execution never authorized'

    async def run(self):
        if self.case.stage != 'created':
            raise ValueError('case execution cannot be resumed')
        status, reason = 'failed', 'incomplete reasoning stage'
        cancelled = False
        try:
            self.case.record('trusted_context', {'policy': asdict(self.policy),
                'read_access': self.ctx.read_access, 'reviews': [asdict(r) for r in self.ctx.reviews],
                'verification_receipts': {key: receipt.to_dict() for key, receipt in self.ctx.receipts.items()}},
                binding=self.case.binding(self.ctx, self.policy))
            if not self.ctx.read_access:
                raise PermissionError('investigation access denied by host')
            self._sync_evidence()
            self._accept_assessment(await self._stage('investigation', AssessmentSubmission))
            for revision in range(2):
                step = 'proposal_readiness' if self.assessment.outcome == 'finding' else 'publication'
                decision = self._assure(step)
                feedback = self._feedback(decision)
                if self._ready(decision):
                    break
                if decision.outcome == 'deny' or revision == 1 or not any(f['kind'] == 'evidence' for f in feedback):
                    break
                self.case.record('feedback_delivered', {'requirements': feedback, 'revision_budget_remaining': 1})
                self._accept_assessment(await self._stage('revision', AssessmentSubmission, feedback))
            if not self._ready(decision):
                status, reason = ('blocked' if decision.outcome == 'deny' else 'provisional'), 'assurance requirements unresolved'
            elif self.assessment.outcome == 'clean':
                status, reason = 'completed', 'clean investigation; no remediation finding'
            elif self.assessment.outcome == 'inconclusive':
                status, reason = 'provisional', 'inconclusive investigation'
            elif 'propose' not in self.case.identity.capabilities:
                status, reason = 'blocked', 'case scope does not permit proposal drafting'
            else:
                # Readiness is a prerequisite for entering the proposal stage.
                submission = await self._stage('proposal', ProposalSubmission)
                status, reason = self._review_proposal(submission, decision)
        except asyncio.CancelledError:
            cancelled = True
            reason = 'stage cancelled'
            self.case.record('stage_error', {'type': 'CancelledError', 'reason': reason})
        except Exception as exc:
            # Do not serialize arbitrary SDK exceptions, which can contain credentials.
            status = 'blocked' if isinstance(exc, PermissionError) else 'failed'
            reason = 'stage failed; inspect recorded input/output and error type'
            self.case.record('stage_error', {'type': type(exc).__name__, 'reason': reason})
        self.case.status = status
        self.case.record('outcome', {'status': status, 'reason': reason, 'verification': 'not_attempted',
                                    'execution_authorized': False})
        self.case.transition('publication', reason)
        # All authoritative decisions are recomputed immediately before publication.
        if self.decisions and self.assessment:
            latest = self.decisions[-1]
            if not decision_is_current(latest, self.assessment, self.proposal, self.ctx, self.policy):
                if self.case.status != 'failed':
                    self.case.status = 'provisional'
                self.case.obligations += ('Prior assurance is stale; a fresh host evaluation is required.',)
                self.case.record('stale_decision', {'reason': 'inputs changed after assurance'})
        report = Report(run_id=self.case.identity.case_id, window=self.case.identity.window,
                        git_sha=self.case.identity.source_commit, findings=[self.finding] if self.finding else [],
                        verification_receipts=dict(self.ctx.receipts),
                        extra_blind_spots=list(self.case.obligations), investigation_case=self.case.to_dict())
        try:
            path = write(report, self.reports_dir)
        except Exception as exc:
            self.case.status = 'failed'
            self.case.record('publication_error', {'type': type(exc).__name__})
            self.case.transition('finished', 'publication failed; case retained')
            raise
        self.case.record('published', {'path': str(path)})
        self.case.transition('finished', 'host published immutable report')
        if cancelled:
            raise asyncio.CancelledError
        return {'run_id': self.case.identity.case_id, 'report': str(path), 'case': str(self.case.storage),
                'status': self.case.status, 'is_error': self.case.status == 'failed'}
