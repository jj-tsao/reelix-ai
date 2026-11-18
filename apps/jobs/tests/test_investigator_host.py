"""Offline host-transition guarantees. No model, telemetry or production access."""
import asyncio
from dataclasses import asdict, replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from reelix_eval.case import CaseIdentity, InvestigationCase
from reelix_eval.orchestration import HostOrchestrator
from reelix_eval.trust import HumanReview, Policy, digest, evaluate
from test_investigator_trust import fixture, review
from reelix_eval.report import finding_from_dict


class HostTests(unittest.IsolatedAsyncioTestCase):
    def setup_case(self, *, missing=False, policy=Policy(), timeout=1.):
        root = Path(self.enterContext(TemporaryDirectory()))
        self.ctx, self.a, self.p = fixture()
        self.ctx.case_id, self.ctx.query_ids = 'case', ('q',)
        records = list(self.ctx.evidence._records.values())
        self.ctx.evidence._records.clear()
        ids = {}
        for e in records:
            new = self.ctx.evidence.record(e.kind, e.provenance, e.payload(), case_id='case', query_ids=('q',) if e.kind == 'runtime' else ())
            ids[e.evidence_id] = new.evidence_id
        self.a = self.a.model_copy(update={
            'observations': tuple(o.model_copy(update={'evidence_id': ids[o.evidence_id]}) for o in self.a.observations),
            'runtime_preconditions': tuple(o.model_copy(update={'evidence_id': ids[o.evidence_id]}) for o in self.a.runtime_preconditions),
            'source_refs': tuple(ids[r] for r in self.a.source_refs),
            'disconfirming_refs': tuple(ids[r] for r in self.a.disconfirming_refs)})
        self.p = self.p.model_copy(update={'preconditions': self.a.runtime_preconditions})
        self.finding = asdict(finding_from_dict(dict(title='Synthetic symptom', symptom='Fit is zero', evidence='query q',
            hypothesis='Enabled path may cause fit', confidence='low', proposed_fix='', query_ids=['q'])))
        self.a = self.a.model_copy(update={'finding_sha256': digest(self.finding)})
        if missing:
            self.a = self.a.model_copy(update={'observations': (self.a.observations[0].model_copy(update={'evidence_id': 'missing'}),)})
        identity = CaseIdentity('case', 'Synthetic investigation', 'frozen', ('q',), 'base', policy.revision)
        self.case = InvestigationCase(identity, root / 'cases')
        self.calls = []
        self.evaluator = Mock(wraps=evaluate)
        self.host = HostOrchestrator(self.case, self.ctx, self.execute, root / 'reports',
            policy=policy, evaluator=self.evaluator, timeout_seconds=timeout)
        self.behavior = None
        return self.host

    def assessment(self):
        return dict(case_id='case', policy_revision=self.host.policy.revision, source_revision='base',
                    assessment=self.a.model_dump(mode='json'), finding=self.finding)

    def proposal(self):
        return dict(case_id='case', policy_revision=self.host.policy.revision, source_revision='base',
                    assessment_sha256=digest(self.host.assessment), proposal=self.p.model_dump(mode='json'))

    async def execute(self, request):
        self.calls.append(request.stage)
        if self.behavior:
            result = self.behavior(request)
            if asyncio.iscoroutine(result):
                result = await result
            if result is not None:
                return result
        return self.proposal() if request.stage == 'proposal' else self.assessment()

    def transitions(self):
        return [json.loads(e.payload_json)['to'] for e in self.case.history if e.kind == 'transition']

    async def test_valid_assessment_automatically_assured_and_approval_remains_required(self):
        host = self.setup_case()
        result = await host.run()
        self.assertEqual(self.calls, ['investigation', 'proposal'])
        self.assertEqual(self.evaluator.call_count, 2)
        self.assertEqual(host.decisions[-1].outcome, 'request_evidence')  # semantic reviews absent
        self.assertEqual(result['status'], 'provisional')
        self.assertEqual(self.transitions(), ['investigation', 'assurance', 'proposal', 'policy', 'publication', 'finished'])
        self.assertFalse(host.decisions[-1].execution_authorized)

    async def test_missing_malformed_or_early_proposal_cannot_advance(self):
        for bad in ({}, {'assessment': {}}, {'proposal': {}}, {'conditions': {'finding.bound': 'satisfied'}}):
            host = self.setup_case()
            self.behavior = lambda _: bad
            result = await host.run()
            self.assertEqual(result['status'], 'failed')
            self.assertNotIn('assurance', self.transitions())
            self.assertNotIn('proposal', self.transitions())
            self.assertEqual(self.evaluator.call_count, 0)

    async def test_contradictory_observation_fails_closed_after_one_revision(self):
        host = self.setup_case()
        self.a = self.a.model_copy(update={'observations': (self.a.observations[0].model_copy(update={'expected_json': '99'}),)})
        await host.run()
        self.assertEqual(self.calls, ['investigation', 'revision'])
        self.assertEqual(self.case.status, 'provisional')
        self.assertTrue(any(c.status == 'unsatisfied' and c.condition_id == 'facts.corroborated' for c in host.decisions[-1].evaluation.conditions))

    async def test_actionable_feedback_revision_and_fresh_snapshot(self):
        host = self.setup_case(missing=True)
        def improve(request):
            if request.stage == 'revision':
                feedback = json.loads(request.input_json)['feedback']
                self.assertTrue(any(f['condition_id'] == 'evidence.resolves' and f['next_action'] for f in feedback))
                e = self.ctx.evidence.record('runtime', 'synthetic:new', {'fit': 0}, case_id='case', query_ids=('q',))
                self.a = self.a.model_copy(update={'observations': (self.a.observations[0].model_copy(update={'evidence_id': e.evidence_id}),)})
        self.behavior = improve
        result = await host.run()
        self.assertEqual(self.calls, ['investigation', 'revision', 'proposal'])
        self.assertEqual(self.evaluator.call_count, 3)
        self.assertNotEqual(host.decisions[0].evaluation.evidence_snapshot, host.decisions[1].evaluation.evidence_snapshot)
        published = json.loads(Path(result['report']).with_name('findings.json').read_text())
        self.assertEqual(len([e for e in published['investigation_case']['history'] if e['kind'] == 'assurance']), 3)

    async def test_exhausted_revision_preserves_uncertainty_and_history(self):
        host = self.setup_case(missing=True)
        await host.run()
        self.assertEqual(self.calls, ['investigation', 'revision'])
        self.assertEqual(self.case.status, 'provisional')
        self.assertEqual(len([e for e in self.case.history if e.kind == 'assessment_accepted']), 2)
        self.assertTrue(self.case.obligations)
        self.assertEqual(self.evaluator.call_count, 2)

    async def test_agent_authority_injections_fail_closed(self):
        for field, value in (('conditions', {}), ('approval', True), ('verification_receipt', {}), ('evidence', {'invented': {}})):
            host = self.setup_case()
            self.behavior = lambda _: {**self.assessment(), field: value}
            await host.run()
            self.assertEqual(self.case.status, 'failed')
            self.assertEqual(self.evaluator.call_count, 0)
        host = self.setup_case()
        self.finding['verified'] = True
        self.a = self.a.model_copy(update={'finding_sha256': digest(self.finding)})
        await host.run()
        self.assertEqual(self.case.status, 'failed')

    async def test_clean_case_without_invented_finding(self):
        host = self.setup_case()
        self.a = self.a.model_copy(update={'outcome': 'clean', 'finding_id': 'clean',
            'finding_sha256': digest({'outcome': 'clean'}), 'causal_hypothesis': '', 'mechanism': ''})
        self.finding = None
        result = await host.run()
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(self.calls, ['investigation'])
        self.assertEqual(self.evaluator.call_count, 1)
        payload = json.loads(Path(result['report']).with_name('findings.json').read_text())
        self.assertEqual(payload['findings'], [])

    async def test_prohibited_target_denied_regardless_of_confidence(self):
        host = self.setup_case()
        self.finding['confidence'] = 'high'
        self.a = self.a.model_copy(update={'finding_sha256': digest(self.finding)})
        self.p = self.p.model_copy(update={'target': '../production.py'})
        await host.run()
        self.assertEqual(host.decisions[-1].outcome, 'deny')
        self.assertEqual(self.case.status, 'blocked')

    async def test_bound_reviews_allow_sandbox_but_never_execution(self):
        for approval, expected in ((False, 'require_approval'), (True, 'sandbox_candidate')):
            host = self.setup_case()
            self.ctx.findings = {self.a.finding_id: self.a.finding_sha256}
            self.ctx.finding_query_ids = {self.a.finding_id: ('q',)}
            review(self.ctx, self.a, self.p, approval=approval)
            await host.run()
            self.assertEqual(host.decisions[-1].outcome, expected)
            self.assertFalse(host.decisions[-1].execution_authorized)

    async def test_unsupported_verification_is_not_missing_diagnostic_evidence(self):
        host = self.setup_case()
        self.p = self.p.model_copy(update={'action_type': 'orchestrator_code_change',
            'target': 'packages/python/reelix_agent/orchestrator/orchestrator_agent.py', 'verification': None})
        await host.run()
        self.assertEqual(host.decisions[-1].outcome, 'require_approval')
        self.assertTrue(any('Sandbox unavailable' in r for r in host.decisions[-1].requirements))

    async def test_snapshot_or_policy_mutation_invalidates_progression(self):
        for mutation in ('evidence', 'policy'):
            host = self.setup_case()
            def change(request):
                if request.stage == 'proposal':
                    if mutation == 'evidence':
                        self.ctx.evidence.record('runtime', 'later', {}, case_id='case', query_ids=('q',))
                    else:
                        self.host.policy = replace(self.host.policy, version='changed')
            self.behavior = change
            await host.run()
            self.assertEqual(self.case.status, 'failed')
            self.assertIsNone(host.proposal)
            self.assertNotIn('policy', self.transitions())

    async def test_sdk_failure_timeout_and_cancellation_retain_case(self):
        for failure in ('error', 'timeout', 'cancel'):
            host = self.setup_case(timeout=.01)
            async def fail(_):
                if failure == 'error':
                    raise RuntimeError('synthetic error')
                if failure == 'cancel':
                    raise asyncio.CancelledError()
                await asyncio.sleep(1)
            self.behavior = fail
            if failure == 'cancel':
                with self.assertRaises(asyncio.CancelledError):
                    await host.run()
            else:
                await host.run()
            self.assertEqual(self.case.status, 'failed')
            self.assertEqual(self.case.stage, 'finished')
            self.assertTrue(any(e.kind == 'stage_error' for e in self.case.history))
            self.assertTrue(list(self.case.storage.glob('*.json')))

    async def test_publication_failure_retains_failed_case(self):
        host = self.setup_case()
        (host.reports_dir / 'case').mkdir(parents=True)
        with self.assertRaises(ValueError):
            await host.run()
        self.assertEqual(self.case.status, 'failed')
        self.assertEqual(self.case.stage, 'finished')
        self.assertTrue(any(e.kind == 'publication_error' for e in self.case.history))

    async def test_no_remediation_is_valid_without_fabricating_proposal(self):
        host = self.setup_case()
        self.behavior = lambda request: {**self.proposal(), 'proposal': None, 'no_action_reason': 'No safe corrective action identified'} if request.stage == 'proposal' else None
        await host.run()
        self.assertIsNone(host.proposal)
        self.assertEqual(self.case.status, 'provisional')
        self.assertNotIn('policy', self.transitions())
        self.assertTrue(any(e.kind == 'proposal_declined' for e in self.case.history))

    async def test_case_capabilities_and_denied_read_access_are_enforced(self):
        host = self.setup_case()
        self.ctx.read_access = False
        await host.run()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.case.status, 'blocked')
        host = self.setup_case()
        self.case.identity = replace(self.case.identity, capabilities=('telemetry_read', 'source_read'))
        await host.run()
        self.assertEqual(self.calls, ['investigation'])
        self.assertEqual(self.case.status, 'blocked')

    async def test_favorable_decision_cannot_survive_changed_proposal_at_publication(self):
        host = self.setup_case()
        self.ctx.findings = {self.a.finding_id: self.a.finding_sha256}
        self.ctx.finding_query_ids = {self.a.finding_id: ('q',)}
        review(self.ctx, self.a, self.p)
        def mutate_after_evaluation(a, p, step, ctx, policy):
            decision = evaluate(a, p, step, ctx, policy)
            if step == 'sandbox_candidate':
                self.assertEqual(decision.outcome, 'sandbox_candidate')
                host.proposal = p.model_copy(update={'candidate_patch': 'changed'})
            return decision
        host.evaluator = mutate_after_evaluation
        await host.run()
        self.assertEqual(self.case.status, 'provisional')
        self.assertTrue(any(e.kind == 'stale_decision' for e in self.case.history))
