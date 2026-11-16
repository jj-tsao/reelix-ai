"""Controlled M2 comparison of host behavior, not a live LLM quality benchmark."""
import json
from dataclasses import asdict, replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from reelix_eval import report
from reelix_eval.agent import tools
from reelix_eval.trust import (
    AXES, InvestigationAssessment, Observation, digest, evaluate, verify_outcome,
)
from test_investigator_reporting_integrity import finding
from test_investigator_trust import fixture, review
from test_investigator_verification import receipt
from test_investigator_trust_integration import payload


class ControlledComparison(unittest.IsolatedAsyncioTestCase):
    async def test_same_unsupported_actionable_finding_old_writer_vs_m2(self):
        """Old publication accepts prose; M2 requires independent evaluation first."""
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            f=finding(); f.update(confidence='high',proposed_fix='Synthetic curator patch')
            legacy=report.Report('legacy','synthetic',findings=[report.Finding(**f)])
            report.write(legacy,root)
            self.assertTrue((root/'legacy'/'report.md').exists())
            ctx=tools.ToolContext(object(),root/'sets',root/'reports',run_id='m2')
            with patch.object(tools,'_ctx',ctx):
                blocked=await tools.write_report.handler({'window':'synthetic','findings':json.dumps([f])})
                self.assertTrue(blocked['is_error'])
                self.assertFalse((ctx.reports_dir/'m2').exists())
                a=InvestigationAssessment(finding_id='f',finding_sha256=digest(asdict(report.Finding(**f))),
                                          missing_evidence=('Direct runtime evidence unavailable',))
                _,_,p=fixture()
                decision=payload(await tools.assess_trust.handler({'finding':json.dumps(f),
                    'assessment':a.model_dump_json(),'proposal':p.model_dump_json(),'step':'remediation_proposal'}))
                self.assertEqual(decision['decision']['outcome'],'request_evidence')
                published=payload(await tools.write_report.handler({'window':'synthetic','findings':json.dumps([f])}))
                saved=json.loads((Path(published['report']).parent/'findings.json').read_text())
                self.assertFalse(saved['trust_decisions'][0]['execution_authorized'])
                self.assertEqual(saved['trust_decisions'][0]['outcome'],'request_evidence')
                self.assertEqual(saved['findings'][0]['confidence'],'high')
                # Confidence is retained as agent prose, and has zero policy authority.

    async def test_clean_control_still_publishes_no_finding(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);ctx=tools.ToolContext(object(),root/'sets',root/'reports',run_id='clean')
            with patch.object(tools,'_ctx',ctx):
                result=payload(await tools.write_report.handler({'window':'synthetic','findings':'[]'}))
            saved=json.loads((Path(result['report']).parent/'findings.json').read_text())
            self.assertEqual(saved['findings'],[])
            self.assertEqual(saved['trust_decisions'],[])

    async def test_controlled_unknown_contradiction_review_and_staleness(self):
        ctx,a,p=fixture()
        states=[]
        states.append(evaluate(a,p,'sandbox_candidate',ctx).outcome)
        bad=a.model_copy(update={'observations':(a.observations[0].model_copy(update={'expected_json':'1'}),)})
        review(ctx,bad,p)
        states.append(evaluate(bad,p,'sandbox_candidate',ctx).outcome)
        review(ctx,a,p,approval=False)
        states.append(evaluate(a,p,'sandbox_candidate',ctx).outcome)
        review(ctx,a,p)
        states.append(evaluate(a,p,'sandbox_candidate',ctx).outcome)
        p=p.model_copy(update={'candidate_patch':'Modified after review'})
        states.append(evaluate(a,p,'sandbox_candidate',ctx).outcome)
        self.assertEqual(states,['request_evidence','request_evidence','require_approval','sandbox_candidate','request_evidence'])


class VerificationObligations(unittest.TestCase):
    def test_trusted_receipt_outcomes_and_plan_binding(self):
        ctx,a,p=fixture(); old=receipt()
        cases=p.verification.case_ids
        good=replace(old,case_ids=cases,evaluated_case_ids=cases,
                     policy=replace(old.policy,min_cases=20))
        plan=p.verification.model_copy(update={'baseline_revision':good.baseline.loaded,
                    'candidate_revision':good.candidate.loaded,'evalset_sha256':good.evalset_sha256})
        p=p.model_copy(update={'verification':plan,'base_revision':good.baseline.loaded,
                              'candidate_revision':good.candidate.loaded})
        def check(r):
            ctx.receipts[r.receipt_id]=r
            return verify_outcome(p,r.receipt_id,ctx)
        self.assertEqual(check(good),'improved')
        self.assertEqual(check(replace(good,attempted=False,execution_completed=False,outputs_valid=False,
            evaluation_valid=False,candidate=None,axes=())),'not_attempted')
        self.assertEqual(check(replace(good,execution_completed=False)),'failed')
        self.assertEqual(check(replace(good,evaluation_valid=False)),'inconclusive')
        self.assertEqual(check(replace(good,evalset_sha256='different')),'inconclusive')
        self.assertEqual(check(replace(good,case_ids=cases[:-1])),'inconclusive')
        flat=replace(good,axes=tuple((axis,3,3,0.1) for axis in AXES[:-1])+((AXES[-1],0,0,0),))
        self.assertEqual(check(flat),'criteria_not_satisfied')
        regression=replace(good,axes=tuple((axis,3,4 if axis!='avg_novelty' else 2,0.1) for axis in AXES[:-1])+((AXES[-1],0,0,0),))
        self.assertEqual(check(regression),'criteria_not_satisfied')
        # A different improving axis cannot satisfy the plan's designated axis.
        different=replace(good,axes=tuple((axis,3,3 if axis==plan.improvement_axis else 4,0.1) for axis in AXES[:-1])+((AXES[-1],0,0,0),))
        self.assertEqual(check(different),'criteria_not_satisfied')
