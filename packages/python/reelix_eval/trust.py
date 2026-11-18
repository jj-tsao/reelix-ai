"""Independent, in-process operational standards. No result grants execution rights.

Only Assessment/Proposal are accepted from the Investigator. Evidence and reviews
are installed by host code; semantic sufficiency is unknown without a bound human
review. A quote's existence never proves its causal interpretation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from reelix_eval.verification import AcceptancePolicy, VerificationReceipt


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)


Text = Annotated[str, StringConstraints(strict=True, strip_whitespace=True)]


class Observation(Input):
    evidence_id: Text = Field(min_length=1)
    # A JSON pointer into an immutable host observation, with an exact value.
    pointer: Text
    expected_json: Text
    description: Text = Field(min_length=1)


class InvestigationAssessment(Input):
    outcome: Literal['finding', 'clean', 'inconclusive'] = 'finding'
    finding_id: Text = Field(min_length=1)
    finding_sha256: Text = Field(min_length=1)
    observations: tuple[Observation, ...] = ()
    source_refs: tuple[Text, ...] = ()
    mechanism: Text = ''
    causal_hypothesis: Text = ''
    runtime_preconditions: tuple[Observation, ...] = ()
    alternatives: tuple[Text, ...] = ()
    disconfirming_refs: tuple[Text, ...] = ()
    missing_evidence: tuple[Text, ...] = ()
    uncertainties: tuple[Text, ...] = ()
    contradictions: tuple[Text, ...] = ()
    unsupported_assumptions: tuple[Text, ...] = ()


class VerificationPlan(Input):
    baseline_controls_before_candidate: Literal[True] = True
    evalset_sha256: Text = Field(min_length=1)
    case_ids: tuple[Text, ...]
    baseline_revision: Text = Field(min_length=1)
    candidate_revision: Text = Field(min_length=1)
    unchanged_controls: int = Field(ge=2)
    min_cases: int = Field(ge=20)
    improvement_axis: Literal['avg_relevance', 'avg_novelty', 'avg_spec_fidelity', 'avg_list_coherence']
    min_gain: float = Field(ge=0.3, allow_inf_nan=False)
    regression_axes: tuple[Text, ...]
    failure_handling: Text = Field(min_length=1)
    abort_when: Text = Field(min_length=1)
    inconclusive_when: Text = Field(min_length=1)


class RemediationProposal(Input):
    finding_id: Text = Field(min_length=1)
    action_type: Literal['curator_code_change', 'curator_prompt_change', 'orchestrator_code_change', 'retrieval_code_change', 'ranking_code_change', 'production_execution']
    target: Text = Field(min_length=1)
    base_revision: Text = Field(min_length=1)
    candidate_revision: Text = Field(min_length=1)
    candidate_patch: Text = Field(min_length=1)
    expected_effect: Text = Field(min_length=1)
    affected_scope: tuple[Text, ...] = Field(min_length=1)
    risks: tuple[Text, ...] = Field(min_length=1)
    preconditions: tuple[Observation, ...] = ()
    reversibility: Text = Field(min_length=1)
    verification: VerificationPlan | None = None


def digest(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode='json')
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    kind: str
    provenance: str
    payload_json: str
    case_id: str = ''
    query_ids: tuple[str, ...] = ()

    def payload(self):
        return json.loads(self.payload_json)


@dataclass
class EvidenceResolver:
    """Host-only registry. Never populate from assessment/proposal arguments."""
    _records: dict[str, Evidence] = field(default_factory=dict)

    def record(self, kind: str, provenance: str, payload: Any, *, case_id: str = '', query_ids: tuple[str, ...] = ()) -> Evidence:
        encoded = json.dumps(payload, sort_keys=True, allow_nan=False)
        key = digest([kind, provenance, encoded, case_id, query_ids])
        record = Evidence(key, kind, provenance, encoded, case_id, query_ids)
        self._records[key] = record
        return record

    def resolve(self, key: str) -> Evidence | None:
        return self._records.get(key)

    @property
    def snapshot(self) -> str:
        return digest([asdict(v) for _, v in sorted(self._records.items())])


Status = Literal['satisfied', 'unsatisfied', 'unknown', 'not_applicable']
Step = Literal['proposal_readiness', 'publication', 'read_only', 'remediation_proposal', 'sandbox_candidate', 'production_execution']
Outcome = Literal['proceed', 'read_only_permitted', 'request_evidence', 'deny', 'require_approval', 'sandbox_candidate']


@dataclass(frozen=True)
class ConditionResult:
    condition_id: str
    status: Status
    evidence_refs: tuple[str, ...]
    rationale: str
    next_action: str | None
    method: str


@dataclass(frozen=True)
class TrustEvaluation:
    assessment_sha256: str
    proposal_sha256: str | None
    policy_revision: str
    policy_version: str
    evidence_snapshot: str
    context_sha256: str
    step: Step
    conditions: tuple[ConditionResult, ...]
    required_conditions: tuple[str, ...]


@dataclass(frozen=True)
class PolicyDecision:
    outcome: Outcome
    evaluation: TrustEvaluation
    requirements: tuple[str, ...]
    # Read-only access can continue when authorized, even with unknown semantics.
    read_only_permitted: bool
    execution_authorized: bool = False


@dataclass(frozen=True)
class Policy:
    version: str = 'reelix-m2-host-v1'
    targets: tuple[tuple[str, str], ...] = (
        ('curator_code_change', 'packages/python/reelix_agent/curator/curator_agent.py'),
        ('curator_code_change', 'packages/python/reelix_agent/curator/curator_tiers.py'),
        ('curator_prompt_change', 'packages/python/reelix_agent/curator/curator_prompts.py'),
    )
    proposal_targets: tuple[tuple[str, str], ...] = (
        ('orchestrator_code_change', 'packages/python/reelix_agent/orchestrator/orchestrator_agent.py'),
        ('orchestrator_code_change', 'packages/python/reelix_agent/orchestrator/orchestrator_prompts.py'),
        ('retrieval_code_change', 'packages/python/reelix_agent/tools/recommendation_tool.py'),
        ('ranking_code_change', 'packages/python/reelix_ranking/rrf.py'),
        ('ranking_code_change', 'packages/python/reelix_ranking/diversification.py'),
        ('retrieval_code_change', 'packages/python/reelix_retrieval/base_retriever.py'),
        ('retrieval_code_change', 'packages/python/reelix_models/cross_encoder_reranker.py'),
    )
    require_human_approval: bool = True

    @property
    def revision(self):
        return digest(asdict(self))


@dataclass(frozen=True)
class HumanReview:
    """Installed by a trusted host caller, never an agent-facing tool.

    Full subject binding makes edits, new evidence and revision changes require
    review again. Reviews are contextual judgments, not causal proof.
    """
    subject: str
    condition_id: str
    accepted: bool
    reviewer: str
    rationale: str
    evidence_refs: tuple[str, ...]


@dataclass
class TrustedContext:
    evidence: EvidenceResolver = field(default_factory=EvidenceResolver)
    # IDs are stable within a run; digests come from the validated Finding.
    findings: dict[str, str] = field(default_factory=dict)
    case_id: str = ''
    query_ids: tuple[str, ...] = ()
    finding_query_ids: dict[str, tuple[str, ...]] = field(default_factory=dict)
    current_revision: str = 'unknown'
    read_access: bool = True
    reviews: tuple[HumanReview, ...] = ()
    receipts: dict[str, VerificationReceipt] = field(default_factory=dict)

    def subject(self, assessment, proposal, policy):
        return digest([digest(assessment), digest(proposal) if proposal else None,
                       policy.revision, self.evidence.snapshot, self.current_revision,
                       self.read_access, sorted(self.findings.items()), self.case_id, self.query_ids,
                       sorted(self.finding_query_ids.items())])


def _pointer(payload, pointer):
    if pointer == '':
        return payload
    if not pointer.startswith('/'):
        raise ValueError('expected JSON pointer')
    for part in pointer[1:].split('/'):
        if re.search(r'~(?![01])', part):
            raise ValueError('invalid JSON pointer escape')
        part = part.replace('~1', '/').replace('~0', '~')
        if isinstance(payload, list):
            if not re.fullmatch(r'0|[1-9][0-9]*', part):
                raise ValueError('invalid array index')
            payload = payload[int(part)]
        elif isinstance(payload, dict):
            payload = payload[part]
        else:
            raise ValueError('pointer traverses scalar')
    return payload


def _in_scope(record, ctx):
    return bool(record and (not ctx.case_id or (record.case_id == ctx.case_id
        and (record.kind != 'runtime' or (record.query_ids and set(record.query_ids) <= set(ctx.query_ids))))))


def _corroborate(claims, ctx, finding_id=None):
    if not claims:
        return 'unknown'
    unresolved = False
    for claim in claims:
        record = ctx.evidence.resolve(claim.evidence_id)
        if not _in_scope(record, ctx):
            unresolved = True
            continue
        if finding_id in ctx.finding_query_ids and not set(record.query_ids) <= set(ctx.finding_query_ids[finding_id]):
            return 'unsatisfied'
        # Source text and model judge opinions cannot corroborate runtime facts.
        if record.kind != 'runtime':
            unresolved = True
            continue
        try:
            actual = _pointer(record.payload(), claim.pointer)
            expected = json.loads(claim.expected_json)
            if digest(actual) != digest(expected):
                return 'unsatisfied'
        except (KeyError, IndexError, ValueError, TypeError):
            return 'unsatisfied'
    return 'unknown' if unresolved else 'satisfied'


AXES = ('avg_relevance', 'avg_novelty', 'avg_spec_fidelity', 'avg_list_coherence', 'spec_violation_rate_judge')


def evaluate(assessment: InvestigationAssessment, proposal: RemediationProposal | None,
             step: Step, ctx: TrustedContext, policy: Policy = Policy()) -> PolicyDecision:
    if step not in ('proposal_readiness', 'publication', 'read_only', 'remediation_proposal', 'sandbox_candidate', 'production_execution'):
        raise ValueError('unsupported next step')
    subject = ctx.subject(assessment, proposal, policy)
    results = []

    def add(cid, status, rationale, next_action=None, refs=(), method='deterministic'):
        results.append(ConditionResult(cid, status, tuple(refs), rationale,
                                       next_action if status not in ('satisfied', 'not_applicable') else None, method))

    def semantic(cid, action, refs=(), represented=True):
        if not represented:
            add(cid, 'unsatisfied', 'Required reasoning inputs are missing.', action, refs)
            return
        reviews = [r for r in ctx.reviews if r.subject == subject and r.condition_id == cid
                   and r.reviewer.strip() and r.rationale.strip() and r.evidence_refs
                   and all(_in_scope(ctx.evidence.resolve(e), ctx) for e in r.evidence_refs)]
        if reviews:
            r = reviews[-1]
            add(cid, 'satisfied' if r.accepted else 'unsatisfied', r.rationale, action,
                r.evidence_refs, 'bound_human_review:' + r.reviewer)
        else:
            add(cid, 'unknown', 'Structural presence does not establish semantic adequacy.', action, refs, 'semantic_requires_review')

    refs = tuple(dict.fromkeys([o.evidence_id for o in assessment.observations + assessment.runtime_preconditions]
                              + list(assessment.source_refs) + list(assessment.disconfirming_refs)
                              + ([o.evidence_id for o in proposal.preconditions] if proposal else [])))
    add('evidence.resolves', 'satisfied' if refs and all(_in_scope(ctx.evidence.resolve(r), ctx) for r in refs) else 'unknown',
        'References checked against host observations.', 'Fetch missing observations through host tools.', refs)
    add('facts.separated', 'satisfied' if assessment.observations and assessment.mechanism and assessment.causal_hypothesis else 'unsatisfied',
        'Typed observations, mechanism and hypothesis are distinct fields; this checks representation only.',
        'Separate measured symptoms, source mechanism and provisional causal hypothesis.')
    add('facts.corroborated', _corroborate(assessment.observations, ctx, assessment.finding_id),
        'Exact runtime fields checked; descriptions remain interpretations.', 'Read query detail and cite exact runtime fields.',
        [o.evidence_id for o in assessment.observations])
    semantic('alternatives.adequate', 'Investigate an alternative and a disconfirming case; obtain bound human review.', assessment.disconfirming_refs, bool(assessment.alternatives and assessment.disconfirming_refs))
    semantic('gaps.explicit', 'Reconcile contradictions and record missing evidence and unsupported assumptions.')
    source_ok = assessment.source_refs and all(_in_scope(ctx.evidence.resolve(r), ctx) and ctx.evidence.resolve(r).kind == 'source' for r in assessment.source_refs)
    if source_ok:
        semantic('mechanism.grounded', 'Have a human review the mechanism against source and observations.', assessment.source_refs)
    else:
        add('mechanism.grounded', 'unknown', 'No resolved source observation.', 'Read relevant permitted source through read_case_source.')
    add('causality.preconditions', _corroborate(assessment.runtime_preconditions, ctx, assessment.finding_id),
        'Runtime predicates checked independently; predicates alone do not establish causality.',
        'Obtain direct runtime corroboration of the hypothesized preconditions.', [o.evidence_id for o in assessment.runtime_preconditions])
    semantic('causality.adequate', 'Obtain human review of causal precondition relevance and competing explanations.')
    bound = ctx.findings.get(assessment.finding_id) == assessment.finding_sha256
    add('finding.bound', 'satisfied' if bound and (proposal is None or proposal.finding_id == assessment.finding_id) else 'unsatisfied',
        'Finding ID and content digest checked against host registration.', 'Register the exact finding and bind its digest.')

    action_ids = ('action.scope', 'action.revision', 'action.preconditions', 'action.relevance', 'risk.bounded',
                  'verification.plan', 'verification.measurable', 'verification.outcomes', 'approval.human')
    if proposal is None:
        for cid in action_ids:
            add(cid, 'not_applicable', 'No remediation proposal supplied.')
    else:
        add('action.scope', 'satisfied' if proposal.action_type != 'production_execution' and (proposal.action_type, proposal.target) in policy.targets + policy.proposal_targets else 'unsatisfied',
            'Action and exact target checked against policy allowlist.', 'Choose an exact permitted proposal target.')
        add('action.revision', 'satisfied' if ctx.current_revision != 'unknown' and proposal.base_revision == ctx.current_revision else 'unsatisfied',
            'Base checked against host revision identity.', 'Refresh proposal against the current host revision.')
        add('action.preconditions', _corroborate(proposal.preconditions, ctx, assessment.finding_id),
            'Action predicates require runtime observations.', 'Read direct evidence for required action preconditions.', [o.evidence_id for o in proposal.preconditions])
        semantic('action.relevance', 'Have a human review that the target and patch address this finding.')
        semantic('risk.bounded', 'Describe affected scope, risks and reversibility; obtain bound human review.')
        plan = proposal.verification
        complete = bool(plan and plan.baseline_revision == proposal.base_revision
                        and plan.candidate_revision == proposal.candidate_revision
                        and plan.candidate_revision != plan.baseline_revision
                        and len(set(plan.case_ids)) == len(plan.case_ids) >= plan.min_cases
                        and all(c.strip() for c in plan.case_ids))
        add('verification.plan', 'satisfied' if complete else 'unsatisfied',
            'Frozen cases, paired revisions and independent unchanged controls required.', 'Require attested baseline and two unchanged-control runs before candidate changes, then at least 20 frozen paired cases with matching revisions.')
        measurable = bool(plan and set(plan.regression_axes) == set(AXES))
        add('verification.measurable', 'satisfied' if measurable else 'unsatisfied',
            'Gain must exceed max(0.3, unchanged spread); no regression on any axis.', 'Specify an improvement axis and all five regression guards.')
        add('verification.outcomes', 'satisfied' if plan else 'unsatisfied',
            'Plan schema distinguishes failure, abort and inconclusive outcomes; adequacy remains part of risk review.', 'Define failure handling, abort and inconclusive outcomes.')
        if policy.require_human_approval:
            semantic('approval.human', 'Obtain human approval bound to these exact inputs.')
        else:
            add('approval.human', 'not_applicable', 'This host policy does not require human approval.')

    source_resolved = bool(source_ok)
    add('mechanism.represented', 'satisfied' if source_resolved and assessment.mechanism.strip() and assessment.causal_hypothesis.strip() else 'unsatisfied',
        'Source reference and plausible mechanism represented; semantic adequacy remains unknown until review.',
        'Read relevant source and represent a plausible mechanism separately from the observed symptom.')
    sandbox_supported = bool(proposal and proposal.action_type in ('curator_code_change', 'curator_prompt_change')
                             and (proposal.action_type, proposal.target) in policy.targets)
    add('verification.supported', 'satisfied' if sandbox_supported else 'unknown' if proposal else 'not_applicable',
        'Only curator code/prompt changes have the M1.5 verification mechanism.',
        'Human review or an applicable verification mechanism is required; additional diagnostic evidence cannot enable this sandbox path.')

    required = ['evidence.resolves', 'facts.separated', 'facts.corroborated', 'finding.bound', 'mechanism.grounded']
    if step in ('sandbox_candidate', 'production_execution'):
        required += ['alternatives.adequate', 'gaps.explicit', 'causality.preconditions', 'causality.adequate', *action_ids[:-1]]
    elif step == 'remediation_proposal':
        required += ['action.scope', 'action.revision', 'action.relevance', 'verification.plan', 'verification.measurable', 'verification.outcomes']
    if step == 'proposal_readiness':
        required = ['evidence.resolves', 'facts.corroborated', 'finding.bound', 'facts.separated', 'mechanism.represented']
    if step == 'publication':
        required = ['evidence.resolves', 'facts.corroborated', 'finding.bound']
    if step == 'read_only':
        required = []
    by_id = {r.condition_id: r for r in results}
    missing = tuple(f'{cid}: {by_id[cid].next_action or "Supply the required proposal."}'
                    for cid in required if by_id[cid].status != 'satisfied')
    if step == 'production_execution' or (proposal and by_id['action.scope'].status == 'unsatisfied') or not ctx.read_access:
        outcome = 'deny'
    elif proposal and not sandbox_supported:
        outcome = 'require_approval'
    elif missing:
        outcome = 'request_evidence'
    elif step in ('proposal_readiness', 'publication'):
        outcome = 'proceed'  # Only this bounded workflow transition; never action authority.
    elif step != 'read_only' and proposal is None:
        outcome = 'request_evidence'
    elif step == 'read_only':
        outcome = 'read_only_permitted'
    elif step == 'remediation_proposal':
        outcome = 'require_approval'
    elif policy.require_human_approval and by_id['approval.human'].status != 'satisfied':
        outcome = 'require_approval'
    else:
        outcome = 'sandbox_candidate'
    requirements = missing
    if proposal and not sandbox_supported:
        requirements += ('verification.supported: Sandbox unavailable pending an applicable verification mechanism or human review.',)
    if outcome == 'require_approval' and step not in ('proposal_readiness', 'publication'):
        requirements += ('Obtain bound human approval; no execution authority is granted.',)
    if outcome == 'deny':
        requirements += ('Production execution and targets outside policy are prohibited; evidence access must be authorized.',)
    if step == 'read_only':
        requirements = tuple(f'{r.condition_id}: {r.next_action}' for r in results if r.next_action)
    evaluation = TrustEvaluation(digest(assessment), digest(proposal) if proposal else None,
                                 policy.revision, policy.version, ctx.evidence.snapshot,
                                 digest([subject, [asdict(r) for r in ctx.reviews]]), step,
                                 tuple(results), tuple(required))
    return PolicyDecision(outcome, evaluation, requirements, ctx.read_access)


def decision_is_current(decision, assessment, proposal, ctx, policy=Policy()):
    """Re-evaluate, including changed reviews, rather than treating a result as a token."""
    return decision == evaluate(assessment, proposal, decision.evaluation.step, ctx, policy)


def verify_outcome(proposal: RemediationProposal, receipt_id: str, ctx: TrustedContext) -> str:
    """Interpret existing M1.5 receipts without accepting agent receipt payloads."""
    receipt = ctx.receipts.get(receipt_id)
    plan = proposal.verification
    if receipt is None or plan is None:
        return 'inconclusive'
    if not receipt.attempted:
        return 'not_attempted'
    if not receipt.execution_completed:
        return 'failed'
    if (not receipt.candidate or not receipt.baseline
            or receipt.candidate.loaded != plan.candidate_revision
            or receipt.baseline.loaded != plan.baseline_revision
            or receipt.evalset_sha256 != plan.evalset_sha256
            or set(receipt.case_ids) != set(plan.case_ids)
            or not receipt.revision_matched or not receipt.outputs_valid or not receipt.evaluation_valid):
        return 'inconclusive'
    policy = AcceptancePolicy(plan.min_cases, plan.min_gain, plan.unchanged_controls)
    from dataclasses import replace
    checked = replace(receipt, policy=policy)
    axis = next((a for a in receipt.axes if a[0] == plan.improvement_axis), None)
    gained = bool(axis and axis[2] - axis[1] > max(plan.min_gain, axis[3]))
    return 'improved' if checked.criteria_satisfied and gained else 'criteria_not_satisfied'
