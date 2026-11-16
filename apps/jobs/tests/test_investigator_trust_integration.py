"""Host-tool integration and feedback revisions; no live service calls."""
import json
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from reelix_eval.agent import tools
from reelix_eval.trust import InvestigationAssessment, Observation, digest
from test_investigator_reporting_integrity import finding
from test_investigator_trust import fixture


def payload(result):
    if result.get('is_error'):
        raise AssertionError(result)
    return json.loads(result['content'][0]['text'])


class TrustIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.ctx = tools.ToolContext(object(), self.root/'sets', self.root/'reports', run_id='trust-run')
        self.enterContext(patch.object(tools, '_ctx', self.ctx))

    async def submit(self, f, a, p=None, step='read_only', **extra):
        return await tools.assess_trust.handler(dict(finding=json.dumps(f), assessment=a.model_dump_json(),
            proposal=p.model_dump_json() if p else 'null', step=step, **extra))

    async def test_feedback_revision_and_atomic_report(self):
        f = finding(); f['proposed_fix']='Consider a curator change after review'
        schema = payload(await tools.trust_contracts.handler({'finding':json.dumps(f)}))
        a = InvestigationAssessment(finding_id='case-finding',finding_sha256=schema['finding_sha256'],
                                    missing_evidence=('Need runtime observation and source',))
        initial = payload(await self.submit(f,a))
        self.assertEqual(initial['decision']['outcome'],'request_evidence')
        self.assertIn('Read query detail',json.dumps(initial))
        src = payload(await tools.read_trust_source.handler({'target':'packages/python/reelix_agent/curator/curator_tiers.py'}))
        observed = self.ctx.trust_context.evidence.record('runtime','synthetic:logged-row',{'fit':0})
        a = a.model_copy(update={'source_refs':(src['evidence']['evidence_id'],),
            'observations':(Observation(evidence_id=observed.evidence_id,pointer='/fit',expected_json='0',description='Logged fit zero'),),
            'mechanism':'Source may alter tier assignment', 'causal_hypothesis':'May explain symptom',
            'uncertainties':('Runtime path applicability remains unconfirmed',),
            'missing_evidence':('Need counterfactual and review',)})
        _,_,p=fixture()
        p=p.model_copy(update={'finding_id':a.finding_id,'base_revision':src['revision']})
        result=payload(await self.submit(f,a,p,'remediation_proposal'))
        conditions={c['condition_id']:c for c in result['decision']['evaluation']['conditions']}
        self.assertEqual(conditions['facts.corroborated']['status'],'satisfied')
        self.assertEqual(conditions['mechanism.grounded']['status'],'unknown')
        self.assertEqual(conditions['verification.plan']['status'],'unsatisfied')
        self.assertEqual(len(self.ctx.trust_history),2)
        rep=payload(await tools.write_report.handler({'window':'synthetic','findings':json.dumps([f])}))
        saved=json.loads((Path(rep['report']).parent/'findings.json').read_text())
        self.assertEqual(saved['trust_decisions'][0]['outcome'],'request_evidence')
        self.assertFalse(saved['trust_decisions'][0]['execution_authorized'])
        self.assertEqual(set(saved['proposal_verification'].values()), {'not_attempted'})
        self.assertIn('Independent operational trust',Path(rep['report']).read_text())

    async def test_report_requires_proposal_evaluation_for_fix(self):
        f=finding(); f['proposed_fix']='Candidate change'
        bad=await tools.write_report.handler({'window':'synthetic','findings':json.dumps([f])})
        self.assertTrue(bad['is_error'])
        self.assertFalse(self.ctx.reports_dir.exists())
        key=payload(await tools.trust_contracts.handler({'finding':json.dumps(f)}))['finding_sha256']
        a=InvestigationAssessment(finding_id='f',finding_sha256=key)
        payload(await self.submit(f,a))
        bad=await tools.write_report.handler({'window':'synthetic','findings':json.dumps([f])})
        self.assertTrue(bad['is_error'])
        self.assertFalse(self.ctx.reports_dir.exists())

    async def test_injected_authority_and_identity_rejected(self):
        f=finding(); a=InvestigationAssessment(finding_id='f',finding_sha256='wrong')
        self.assertTrue((await self.submit(f,a))['is_error'])
        key=payload(await tools.trust_contracts.handler({'finding':json.dumps(f)}))['finding_sha256']
        a=a.model_copy(update={'finding_sha256':key})
        self.assertTrue((await self.submit(f,a,approval=True))['is_error'])
        self.assertFalse(self.ctx.trust_context.reviews)
        self.assertFalse(self.ctx.trust_context.receipts)
        self.assertTrue((await tools.read_trust_source.handler({'target':'../../secret'}))['is_error'])

    async def test_tool_evidence_captures_result_not_agent_assertions(self):
        with patch.object(tools.store,'list_windows',return_value=[]):
            result=payload(await tools.list_eval_windows.handler({'days':1}))
        record=self.ctx.trust_context.evidence.resolve(result['_trust_evidence']['evidence_id'])
        self.assertEqual(record.payload()['windows'],[])
        self.assertTrue(record.provenance.startswith('list_eval_windows:'))
        self.assertNotIn('_trust_evidence',record.payload())

    async def test_m2_cannot_execute_even_with_apply_or_favorable_decision(self):
        from importlib import import_module
        run=import_module('reelix_eval.agent.run')
        for mode in (True,False):
            guard=run.build_guard(mode)
            for name,args in (('Bash',{'command':'git status'}),('Write',{'file_path':str(self.root/'x')}),('Edit',{'file_path':str(self.root/'x')})):
                result=await guard(name,args,None)
                self.assertEqual(result.behavior,'deny')
            cfg=run.RunConfig(apply_mode=mode)
            opts=run.build_options(cfg)
            self.assertEqual(set(opts.disallowed_tools),set(run.WRITE_TOOLS))
            self.assertIn('proposal-only',run.build_task(cfg))
