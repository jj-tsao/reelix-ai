"""Synthetic execution records; no model, database or production services."""
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from reelix_eval.verification import AcceptancePolicy, RevisionEvidence, VerificationReceipt
from reelix_eval.agent import tools
from reelix_eval import report
from reelix_eval.replay.curator import CaseReplay, ReplayRun, cases_digest
from reelix_eval.replay.evalset import EvalCase, FrozenCandidate
from reelix_eval.judge.runner import QueryJudgement, ItemJudgement
from test_investigator_reporting_integrity import finding


def revision(name='base',execution='base'):
    files=(('reelix_test/a.py',hashlib.sha256(name.encode()).hexdigest()),)
    digest=hashlib.sha256(json.dumps(dict(files),sort_keys=True).encode()).hexdigest()
    return RevisionEvidence(digest,digest,files,files,'prompt',True,123,execution,'prompt',(('fn','code'),))


def receipt():
    return VerificationReceipt('evalset',('case-1','case-2'),(),revision('candidate','candidate'),
        baseline=revision(),execution_completed=True,outputs_valid=True,evaluation_valid=True,
        controls=(revision(execution='control-1'),revision(execution='control-2')),
        axes=tuple((a,3,4,0.1) for a in ('avg_relevance','avg_novelty','avg_spec_fidelity','avg_list_coherence'))+
             (('spec_violation_rate_judge',0,0,0),),policy=AcceptancePolicy(min_cases=2),
        evaluation_sha256='evaluation',judge_model='mock',evaluated_case_ids=('case-1','case-2'))


class ReceiptTests(unittest.TestCase):
    def test_three_states_and_fail_closed_prerequisites(self):
        good=receipt()
        self.assertTrue(good.verified)
        self.assertIsNone(VerificationReceipt('',(),(),None,attempted=False).verified)
        changes=[dict(execution_completed=False),dict(outputs_valid=False),dict(evaluation_valid=False),
                 dict(baseline=None),dict(candidate=replace(good.candidate,loaded='stale')),
                 dict(candidate=replace(good.candidate,prompt_sha256='stale')),
                 dict(failed_case_ids=('case-1',)),dict(issues=('missing',)),dict(evaluation_sha256=''),
                 dict(case_ids=('case-1',)),dict(case_ids=('case-1','case-1')),
                 dict(controls=()),dict(controls=(good.controls[0],good.controls[0])),
                 dict(controls=(good.baseline,good.controls[1])),
                 dict(candidate=good.baseline),dict(axes=good.axes[:-1]),
                 dict(axes=tuple((a,b,b,0) for a,b,c,n in good.axes)),
                 dict(axes=tuple((a,b,b+.1 if a!='spec_violation_rate_judge' else b,0) for a,b,c,n in good.axes)),
                 dict(axes=tuple((a,b,c,2) for a,b,c,n in good.axes)),
                 dict(axes=(('avg_relevance',4,3,0),)+good.axes[1:])]
        for change in changes:
            with self.subTest(change=change):self.assertIs(replace(good,**change).verified,False)

    def test_report_outputs_share_receipt_decision_and_reject_mismatch(self):
        for rec in (receipt(),replace(receipt(),evaluation_valid=False)):
            f=report.Finding(**finding(verified=rec.verified,verification_id=rec.receipt_id))
            rep=report.Report('test','synthetic',findings=[f],verification_receipts={rec.receipt_id:rec})
            data=rep.to_dict()
            self.assertIs(data['findings'][0]['verified'],rec.verified)
            self.assertIn(rec.receipt_id,rep.to_markdown())
            self.assertIn('successful: acceptance criteria satisfied' if rec.verified else
                          'attempted: acceptance criteria NOT satisfied',rep.to_markdown())
            f.verified=not rec.verified
            with self.assertRaises(report.ReportValidationError):rep.to_dict()


class ScoreReplayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.root=Path(self.enterContext(TemporaryDirectory()))
        self.ctx=tools.ToolContext(object(),self.root,self.root/'reports',verification_policy=AcceptancePolicy(min_cases=2))
        self.enterContext(patch.object(tools,'_ctx',self.ctx))
        self.cases=[EvalCase(f'case-{i}','Synthetic',{'query_text':'Synthetic'},[
            FrozenCandidate(1,'Synthetic',{'id':1})],baseline_served_ids=[1]) for i in (1,2)]
        self.enterContext(patch.object(tools.evalset_mod,'load',return_value=self.cases))
        self.enterContext(patch.object(tools,'build_client',return_value=object()))
        for label in ('base','candidate','control-1','control-2'):
            rev=revision('candidate' if label=='candidate' else 'base',label)
            cs=[CaseReplay(c.query_id,c.query_text,served_ids=[1],fits={1:{'total_fit':6,'category':'strong_match'}},
                           execution_completed=True,outputs_valid=True) for c in self.cases]
            self.ctx.replays[label]=ReplayRun(label,cs,rev,cases_digest(self.cases),True)
        async def judge(client,details,cfg):
            self.assertFalse(cfg.persist)
            score=4 if self.calls==1 else 3
            self.calls+=1
            return [QueryJudgement(d.query_id,d.query_text,spec_fidelity=score,list_coherence=score,
                    items=[ItemJudgement(d.query_id,c.media_id,c.title,d.query_text,relevance=score,
                                         novelty=score,spec_violation=False) for c in d.candidates]) for d in details]
        self.calls=0
        self.judge=self.enterContext(patch.object(tools,'judge_queries',side_effect=judge))

    async def score(self,**extra):
        result=await tools.score_replay.handler(dict(evalset='synthetic',label='candidate',
                    baseline_label='base',control_labels=['control-1','control-2'],**extra))
        self.assertNotIn('is_error',result)
        return json.loads(result['content'][0]['text'])

    async def test_complete_paired_controlled_evaluation_and_report_binding(self):
        data=await self.score()
        self.assertTrue(data['receipt']['verified'])
        self.assertEqual(data['evaluated_cases'],2)
        self.assertEqual(self.calls,4)
        rid=data['receipt_id']
        result=await tools.write_report.handler({'window':'synthetic','findings':json.dumps([finding(verification_id=rid)])})
        self.assertNotIn('is_error',result)
        content=json.loads((self.ctx.reports_dir/'adhoc/findings.json').read_text())
        self.assertIs(content['findings'][0]['verified'],True)

    async def test_incomplete_run_never_judges_survivors_or_certifies(self):
        self.ctx.replays['candidate'].cases[0].outputs_valid=False
        data=await self.score()
        self.assertIs(data['receipt']['verified'],False)
        self.assertEqual(data['requested_cases'],2)
        self.assertEqual(data['evaluated_cases'],0)
        self.assertEqual(data['failed_case_ids'],['case-1'])
        self.judge.assert_not_called()

    async def test_evalset_mismatch_and_unattested_revision_fail_closed(self):
        self.ctx.replays['candidate'].evalset_sha256='different'
        data=await self.score()
        self.assertIs(data['receipt']['verified'],False)
        self.judge.assert_not_called()
        self.ctx.replays['candidate'].evalset_sha256=cases_digest(self.cases)
        self.ctx.replays['candidate'].revision=None
        data=await self.score()
        self.assertFalse(data['receipt']['revision_matched'])
        self.assertIs(data['receipt']['verified'],False)

    async def test_incomplete_judgements_cannot_form_improvement(self):
        self.judge.side_effect=None;self.judge.return_value=[]
        data=await self.score()
        self.assertIs(data['receipt']['verified'],False)
        self.assertFalse(data['receipt']['evaluation_valid'])
        self.assertEqual(data['evaluated_cases'],0)
        self.assertEqual(data['summaries'],[])

    async def test_frozen_baseline_cannot_attest_baseline_revision(self):
        result=await tools.score_replay.handler({'evalset':'synthetic','label':'candidate'})
        data=json.loads(result['content'][0]['text'])
        self.assertIs(data['receipt']['verified'],False)
        self.assertEqual(data['receipt']['decision'],'revision_unverified')

    async def test_agent_cannot_supply_receipt_or_unsupported_claim(self):
        for verification in ({},receipt().to_dict(),{'receipt_id':'invented'}):
            result=await tools.write_report.handler({'window':'synthetic','findings':'[]',
                                                     'verification':json.dumps(verification)})
            self.assertTrue(result.get('is_error'))
        data=await self.score()
        result=await tools.write_report.handler({'window':'synthetic','findings':json.dumps([
                         finding(verified=False,verification_id=data['receipt_id'])])})
        self.assertTrue(result.get('is_error'))

    async def test_partial_judge_coverage_is_explicit_without_subset_aggregate(self):
        original=self.judge.side_effect
        async def partial(*args):
            result=await original(*args)
            return result[:1]
        self.judge.side_effect=partial
        data=await self.score()
        self.assertIs(data['receipt']['verified'],False)
        self.assertEqual(data['requested_cases'],2)
        self.assertEqual(data['evaluated_cases'],1)
        self.assertEqual(data['evaluation_failed_case_ids'],['case-2'])
        self.assertEqual(data['summaries'],[])

    async def test_completed_replay_without_gain_is_unsuccessful(self):
        original=self.judge.side_effect
        async def unchanged(*args):
            self.calls=0
            return await original(*args)
        self.judge.side_effect=unchanged
        data=await self.score()
        self.assertTrue(data['receipt']['execution_completed'])
        self.assertTrue(data['receipt']['outputs_valid'])
        self.assertTrue(data['receipt']['evaluation_valid'])
        self.assertIs(data['receipt']['verified'],False)
        self.assertEqual(data['receipt']['decision'],'criteria_not_satisfied')

    async def test_replay_only_attempt_produces_unsuccessful_receipt(self):
        self.ctx.llm_client=object()
        with patch.object(Path,'exists',return_value=True), \
             patch.object(tools.replay_mod,'replay',new=AsyncMock(return_value=self.ctx.replays['candidate'])):
            result=await tools.replay_curator.handler({'evalset':'synthetic','label':'fresh'})
        data=json.loads(result['content'][0]['text'])
        self.assertIs(data['receipt']['verified'],False)
        self.assertTrue(data['receipt']['attempted'])
        self.assertFalse(data['receipt']['evaluation_valid'])
        repeated=await tools.replay_curator.handler({'evalset':'synthetic','label':'fresh'})
        self.assertTrue(repeated['is_error'])

    async def test_invalid_judge_fields_and_failed_status_are_not_low_scores(self):
        original=self.judge.side_effect
        for field,value in (('spec_fidelity',None),('list_coherence',0),('status','error')):
            async def invalid(*args):
                result=await original(*args)
                setattr(result[0],field,value)
                return result
            self.judge.side_effect=invalid
            data=await self.score()
            self.assertFalse(data['receipt']['evaluation_valid'])
            self.assertIs(data['receipt']['verified'],False)
            self.assertIn('case-1',data['evaluation_failed_case_ids'])
            self.assertEqual(data['summaries'],[])

    async def test_incomplete_control_cannot_certify_candidate(self):
        self.ctx.replays['control-1'].cases.pop()
        data=await self.score()
        self.assertIs(data['receipt']['verified'],False)
        self.assertEqual(data['evaluated_cases'],0)
        self.judge.assert_not_called()


    async def test_judge_exception_is_safe_and_all_requested_groups_are_settled(self):
        import asyncio
        settled=[]
        async def fail(client,details,cfg):
            await asyncio.sleep(0)
            settled.append(True)
            raise RuntimeError('private-secret')
        self.judge.side_effect=fail
        data=await self.score()
        self.assertEqual(len(settled),4)
        self.assertIs(data['receipt']['verified'],False)
        self.assertEqual(data['evaluation_failed_case_ids'],['case-1','case-2'])
        self.assertNotIn('private-secret',json.dumps(data))


    async def test_missing_revision_on_extra_requested_control_is_not_dropped(self):
        self.ctx.replays['unattested']=replace(self.ctx.replays['control-1'],label='unattested',revision=None)
        result=await tools.score_replay.handler({'evalset':'synthetic','label':'candidate',
                   'baseline_label':'base','control_labels':['control-1','control-2','unattested']})
        data=json.loads(result['content'][0]['text'])
        self.assertIs(data['receipt']['verified'],False)
        self.assertEqual(len(data['receipt']['controls']),3)
        self.assertIsNone(data['receipt']['controls'][-1])
        self.assertFalse(data['receipt']['revision_matched'])
