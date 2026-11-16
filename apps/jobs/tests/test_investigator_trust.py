"""Offline policy contracts; synthetic inputs never represent production evidence."""
from dataclasses import replace
import json
import unittest

from pydantic import ValidationError
from reelix_eval.trust import (
    AXES, HumanReview, InvestigationAssessment, Observation, Policy,
    RemediationProposal, TrustedContext, VerificationPlan, decision_is_current,
    digest, evaluate, verify_outcome,
)


def fixture():
    ctx = TrustedContext(current_revision='base', findings={'f': 'finding-digest'})
    runtime = ctx.evidence.record('runtime', 'synthetic:query-1', {'fit': 0, 'enabled': True})
    source = ctx.evidence.record('source', 'synthetic:curator.py@base', {'text': 'if enabled: apply()'})
    obs = Observation(evidence_id=runtime.evidence_id, pointer='/fit', expected_json='0', description='Zero fit')
    predicate = Observation(evidence_id=runtime.evidence_id, pointer='/enabled', expected_json='true', description='Path enabled')
    assessment = InvestigationAssessment(finding_id='f', finding_sha256='finding-digest', observations=(obs,),
        source_refs=(source.evidence_id,), mechanism='Enabled path calls apply', causal_hypothesis='Path may cause symptom',
        runtime_preconditions=(predicate,), alternatives=('Input quality',), disconfirming_refs=(runtime.evidence_id,),
        uncertainties=('Counterfactual is unobserved',))
    plan = VerificationPlan(evalset_sha256='frozen', case_ids=tuple(f'case-{i}' for i in range(20)),
        baseline_revision='base', candidate_revision='candidate', unchanged_controls=2, min_cases=20,
        improvement_axis='avg_relevance', min_gain=0.3, regression_axes=AXES,
        failure_handling='Keep proposal unverified', abort_when='Invalid outputs', inconclusive_when='Missing judge data')
    proposal = RemediationProposal(finding_id='f', action_type='curator_code_change',
        target='packages/python/reelix_agent/curator/curator_tiers.py', base_revision='base',
        candidate_revision='candidate', candidate_patch='Synthetic reference only', expected_effect='Improve relevance',
        affected_scope=('Curator tiers',), risks=('Tier movement',), preconditions=(predicate,),
        reversibility='Discard candidate', verification=plan)
    return ctx, assessment, proposal


def review(ctx, assessment, proposal, policy=Policy(), approval=True):
    ids = ('alternatives.adequate', 'gaps.explicit', 'mechanism.grounded', 'causality.adequate', 'action.relevance', 'risk.bounded')
    if approval:
        ids += ('approval.human',)
    ctx.reviews = tuple(HumanReview(ctx.subject(assessment, proposal, policy), cid, True,
        'synthetic human', 'Synthetic reviewed evidence', assessment.source_refs) for cid in ids)


class TrustContracts(unittest.TestCase):
    def test_inputs_reject_authoritative_fields_and_invalid_types(self):
        ctx, a, p = fixture()
        for value in ({**a.model_dump(), 'conditions': {'mechanism.grounded': 'satisfied'}},
                      {**a.model_dump(), 'approval': True}, {**a.model_dump(), 'finding_id': 1}):
            with self.assertRaises(ValidationError):
                InvestigationAssessment.model_validate(value)
        with self.assertRaises(ValidationError):
            RemediationProposal.model_validate({**p.model_dump(), 'verification_receipt': {}})
        with self.assertRaises(ValidationError):
            a.finding_id = 'changed'
        self.assertEqual(a, InvestigationAssessment.model_validate_json(a.model_dump_json()))

    def test_four_statuses_and_semantic_presence_is_not_proof(self):
        ctx, a, p = fixture()
        d = evaluate(a, None, 'read_only', ctx)
        values = {r.condition_id: r.status for r in d.evaluation.conditions}
        self.assertEqual(values['facts.corroborated'], 'satisfied')
        self.assertEqual(values['mechanism.grounded'], 'unknown')
        self.assertEqual(values['action.scope'], 'not_applicable')
        bad = a.model_copy(update={'finding_sha256': 'wrong'})
        self.assertIn('unsatisfied', [r.status for r in evaluate(bad, None, 'read_only', ctx).evaluation.conditions])
        self.assertTrue(d.read_only_permitted)
        self.assertFalse(d.execution_authorized)

    def test_missing_fabricated_and_contradictory_evidence(self):
        ctx, a, p = fixture()
        for pointer, expected, key, status in (('/fit','1',a.observations[0].evidence_id,'unsatisfied'),
                                               ('/missing','0',a.observations[0].evidence_id,'unsatisfied'),
                                               ('/fit','0','fabricated','unknown'),
                                               ('/text','"if enabled: apply()"',a.source_refs[0],'unknown')):
            obs = a.observations[0].model_copy(update={'pointer':pointer,'expected_json':expected,'evidence_id':key})
            changed = a.model_copy(update={'observations':(obs,)})
            d = evaluate(changed,p,'sandbox_candidate',ctx)
            self.assertEqual(next(r.status for r in d.evaluation.conditions if r.condition_id=='facts.corroborated'),status)
            self.assertEqual(d.outcome,'request_evidence')

    def test_risk_sensitive_branches(self):
        ctx, a, p = fixture()
        self.assertEqual(evaluate(a,p,'sandbox_candidate',ctx).outcome,'request_evidence')
        review(ctx,a,p,approval=False)
        self.assertEqual(evaluate(a,p,'remediation_proposal',ctx).outcome,'require_approval')
        self.assertEqual(evaluate(a,p,'sandbox_candidate',ctx).outcome,'require_approval')
        review(ctx,a,p)
        d=evaluate(a,p,'sandbox_candidate',ctx)
        self.assertEqual(d.outcome,'sandbox_candidate')
        self.assertFalse(d.execution_authorized)
        self.assertEqual(evaluate(a,p,'production_execution',ctx).outcome,'deny')
        self.assertEqual(evaluate(a,None,'sandbox_candidate',ctx).outcome,'request_evidence')
        self.assertEqual(evaluate(a,p.model_copy(update={'target':'../production.py'}),'sandbox_candidate',ctx).outcome,'deny')
        production=p.model_copy(update={'action_type':'production_execution'})
        permissive=Policy(targets=(('production_execution',p.target),),require_human_approval=False)
        self.assertEqual(evaluate(a,production,'sandbox_candidate',ctx,permissive).outcome,'deny')
        ctx.read_access=False
        self.assertEqual(evaluate(a,None,'read_only',ctx).outcome,'deny')

    def test_policy_without_approval_still_requires_evidence(self):
        ctx,a,p=fixture(); policy=Policy(require_human_approval=False)
        self.assertEqual(evaluate(a,p,'sandbox_candidate',ctx,policy).outcome,'request_evidence')
        review(ctx,a,p,policy,approval=False)
        self.assertEqual(evaluate(a,p,'sandbox_candidate',ctx,policy).outcome,'sandbox_candidate')

    def test_decisions_bound_to_all_inputs_and_deterministic(self):
        ctx,a,p=fixture(); review(ctx,a,p)
        d=evaluate(a,p,'sandbox_candidate',ctx)
        self.assertEqual(d,evaluate(a,p,'sandbox_candidate',ctx))
        self.assertTrue(decision_is_current(d,a,p,ctx))
        self.assertFalse(decision_is_current(d,a,p.model_copy(update={'candidate_patch':'changed'}),ctx))
        self.assertFalse(decision_is_current(d,a,p,ctx,Policy(version='next')))
        ctx.evidence.record('runtime','new observation',{'value':1})
        self.assertFalse(decision_is_current(d,a,p,ctx))
        self.assertEqual(evaluate(a,p,'sandbox_candidate',ctx).outcome,'request_evidence')

    def test_unknown_and_not_applicable_cannot_satisfy_hard_conditions(self):
        ctx,a,p=fixture()
        review(ctx,a,p)
        for changed in (p.model_copy(update={'verification':None}),
                        p.model_copy(update={'preconditions':()}),
                        p.model_copy(update={'base_revision':'stale'})):
            self.assertEqual(evaluate(a,changed,'sandbox_candidate',ctx).outcome,'request_evidence')
        self.assertEqual(evaluate(a,None,'sandbox_candidate',ctx).outcome,'request_evidence')

    def test_host_review_rejection_is_not_satisfaction(self):
        ctx,a,p=fixture();review(ctx,a,p)
        ctx.reviews=tuple(replace(r,accepted=False) if r.condition_id=='risk.bounded' else r for r in ctx.reviews)
        self.assertEqual(evaluate(a,p,'sandbox_candidate',ctx).outcome,'request_evidence')

    def test_receipt_is_resolved_only_by_host(self):
        ctx,a,p=fixture()
        self.assertEqual(verify_outcome(p,'agent-invented-receipt',ctx),'inconclusive')
