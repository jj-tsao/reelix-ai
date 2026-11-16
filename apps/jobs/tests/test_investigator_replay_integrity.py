import asyncio
import json
from types import SimpleNamespace
import unittest

from reelix_eval.replay.curator import replay_case, ReplayRun
from reelix_eval.replay.evalset import EvalCase, FrozenCandidate


def case():
    return EvalCase('case-1','Synthetic comedy',{'query_text':'Synthetic comedy'},[
        FrozenCandidate(i,f'Title {i}',{'id':i,'t':f'Title {i}','g':['Comedy'],'k':[],'o':'Synthetic'}) for i in (1,2)
    ],baseline_served_ids=[1,2])


class FakeClient:
    def __init__(self, transform=None): self.transform=transform;self.prompts=[];self.temperatures=[]
    async def chat(self,**kwargs):
        self.prompts.append(kwargs['messages'])
        self.temperatures.append(kwargs['temperature'])
        cards=json.loads(kwargs['messages'][1]['content'].split('Candidates:\n',1)[1])
        items=[dict(media_id=c['id'],genre_fit=2,tone_fit=2,theme_fit=2) for c in cards]
        content=self.transform(items) if self.transform else {'evaluation_results':items}
        raw=content if isinstance(content,str) else json.dumps(content)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=raw,refusal=None),finish_reason='stop')],
                               usage=SimpleNamespace(prompt_tokens=7,completion_tokens=3))


class ReplayCompletenessTests(unittest.IsolatedAsyncioTestCase):
    async def test_incomplete_malformed_and_invalid_scores_are_not_success(self):
        transforms=[lambda rows:{},lambda rows:{'evaluation_results':[]},
                    lambda rows:{'evaluation_results':rows+rows},
                    lambda rows:{'evaluation_results':[dict(rows[0],genre_fit='2')]},
                    lambda rows:{'evaluation_results':[dict(rows[0],tone_fit=True)]},
                    lambda rows:{'evaluation_results':[dict(rows[0],theme_fit=3)]},
                    lambda rows:{'evaluation_results':[dict(rows[0],media_id=999)]},
                    lambda rows:'not json',lambda rows:'{"evaluation_results":[],"evaluation_results":[]}',lambda rows:{'evaluation_results':{}},
                    lambda rows:{'evaluation_results':[{'media_id':rows[0]['media_id']}]},
                    lambda rows:{'evaluation_results':[dict(rows[0],genre_fit=-1)]}]
        for transform in transforms:
            with self.subTest(transform=transform):
                result=await replay_case(case(),FakeClient(transform))
                self.assertFalse(result.ok)
                self.assertFalse(result.outputs_valid)
                self.assertEqual(result.served_ids,[])

    async def test_complete_low_scores_are_valid_not_missing(self):
        c=FakeClient(lambda rows:{'evaluation_results':[dict(r,genre_fit=0,tone_fit=0,theme_fit=0) for r in rows]})
        result=await replay_case(case(),c)
        self.assertTrue(result.ok)
        self.assertTrue(result.outputs_valid)
        self.assertEqual(result.served_ids,[])
        self.assertEqual(result.tier_stats['no_match_count'],2)

    async def test_failed_case_usage_and_denominator_are_not_dropped(self):
        result=await replay_case(case(),FakeClient(lambda rows:{}))
        self.assertFalse(result.ok)
        summary=ReplayRun('test',[result]).summary()
        self.assertEqual(summary['cases'],1)
        self.assertEqual(summary['cases_failed'],1)
        self.assertEqual(summary['total_input_tokens'],14)
        self.assertIsNone(summary['mean_served_overlap'])

    async def test_bad_spec_fails_instead_of_falling_back(self):
        c=case();c.spec_json={'num_recs':'not an integer'}
        client=FakeClient();result=await replay_case(c,client)
        self.assertFalse(result.ok)
        self.assertEqual(client.prompts,[])


if __name__=='__main__':unittest.main()

class FreshRevisionTests(unittest.IsolatedAsyncioTestCase):
    async def test_baseline_candidate_and_expected_mismatch(self):
        import tempfile
        from pathlib import Path
        from reelix_eval.replay.curator import replay
        from reelix_eval.replay.isolated import SOURCE_ROOT, source_manifest, manifest_digest
        # Warm the parent import bindings before editing the isolated candidate.
        from reelix_agent.curator import curator_agent
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in source_manifest(SOURCE_ROOT):
                dest=root/name;dest.parent.mkdir(parents=True,exist_ok=True)
                dest.write_bytes((SOURCE_ROOT/name).read_bytes())
            base_client=FakeClient()
            base=await replay([case()],base_client,label='base',source_root=root,timeout=20)
            self.assertEqual(base.issues,[])
            self.assertTrue(base.revision.matched)
            self.assertTrue(base.ok_cases)
            prompt=root/'reelix_agent/curator/curator_prompts.py'
            prompt.write_text(prompt.read_text()+"\nCURATOR_PROMPT_S = "+repr(curator_agent.CURATOR_PROMPT_S+' SYNTHETIC_CANDIDATE_MARKER')+'\n')
            agent=root/'reelix_agent/curator/curator_agent.py'
            text=agent.read_text()
            # Change a relevant function in the copied revision, without changing production.
            text=text.replace('temperature=0.1','temperature=0.0')
            self.assertNotEqual(text,agent.read_text())
            agent.write_text(text)
            candidate_client=FakeClient()
            candidate=await replay([case()],candidate_client,label='candidate',source_root=root,timeout=20)
            self.assertEqual(candidate.issues,[])
            self.assertTrue(candidate.revision.matched)
            self.assertEqual(base_client.temperatures,[0.1,0.1])
            self.assertEqual(candidate_client.temperatures,[0.0,0.0])
            self.assertNotEqual(base.revision.loaded,candidate.revision.loaded)
            self.assertNotEqual(base.revision.execution_id,candidate.revision.execution_id)
            self.assertNotEqual(base.revision.prompt_sha256,candidate.revision.prompt_sha256)
            self.assertIn('SYNTHETIC_CANDIDATE_MARKER',candidate_client.prompts[0][0]['content'])
            self.assertNotIn('SYNTHETIC_CANDIDATE_MARKER',base_client.prompts[0][0]['content'])
            self.assertNotIn('SYNTHETIC_CANDIDATE_MARKER',curator_agent.CURATOR_PROMPT_S)
            wrong_client=FakeClient()
            wrong=await replay([case()],wrong_client,label='wrong',source_root=root,expected_revision=base.revision.loaded)
            self.assertEqual(wrong_client.prompts,[])
            self.assertFalse(wrong.ok_cases)
            self.assertIn('expected_revision_mismatch',wrong.issues)
            empty=await replay([case()],wrong_client,source_root=root,expected_revision='')
            self.assertIn('expected_revision_mismatch',empty.issues)
            self.assertEqual(wrong_client.prompts,[])

            # Runtime prompt mutation must not pass the source-literal identity check.
            prompt.write_text(prompt.read_text()+"\nCURATOR_PROMPT_S += ' runtime-mutation'\n")
            mismatch_client=FakeClient()
            mismatch=await replay([case()],mismatch_client,label='runtime-mismatch',source_root=root,timeout=20)
            self.assertEqual(mismatch_client.prompts,[])
            self.assertFalse(mismatch.ok_cases)
            self.assertIn('loaded_revision_mismatch',mismatch.issues)

class ReplayFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_truncation_and_refusal_preserve_usage_but_fail_output(self):
        for reason,refusal in (('length',None),('stop','refused'),(None,None)):
            class IncompleteClient(FakeClient):
                async def chat(self,**kwargs):
                    result=await super().chat(**kwargs)
                    result.choices[0].finish_reason=reason
                    result.choices[0].message.refusal=refusal
                    return result
            result=await replay_case(case(),IncompleteClient())
            self.assertFalse(result.ok)
            self.assertFalse(result.execution_completed)
            self.assertEqual(result.input_tokens,14)

    async def test_mixed_valid_and_failed_cases_keep_denominators(self):
        valid=await replay_case(case(),FakeClient())
        failed=await replay_case(case(),FakeClient(lambda rows:{}))
        failed.query_id='case-2'
        summary=ReplayRun('mixed',[valid,failed]).summary()
        self.assertEqual(summary['cases'],2)
        self.assertEqual(summary['aggregate_cases'],1)
        self.assertEqual(summary['failed_case_ids'],['case-2'])
        self.assertEqual(summary['total_input_tokens'],28)
