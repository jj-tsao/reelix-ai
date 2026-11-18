import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from reelix_eval import report
from reelix_eval.agent import tools


def finding(**extra):
    return dict(title="Synthetic symptom", symptom="Observed synthetic symptom",
                evidence="case-1: measured value", hypothesis="Possible mechanism",
                confidence="low", proposed_fix="", query_ids=["case-1"], **extra)


class ReportInputTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.ctx = tools.ToolContext(object(), self.root/'sets', self.root/'reports', run_id='run')
        self.enterContext(patch.object(tools, '_ctx', self.ctx))

    async def call(self, value):
        return await tools.write_report.handler({'window':'synthetic', 'findings':value})

    async def test_malformed_findings_cannot_publish_clean_report(self):
        for value in ('{private-secret', '', '{"title":"private-secret"', '[NaN]',
                      '[{"title":"private-secret","title":"duplicate"}]'):
            with self.subTest(value=value):
                result = await self.call(value)
                self.assertTrue(result.get('is_error'))
                self.assertNotIn('private-secret', result['content'][0]['text'])
                self.assertFalse((self.ctx.reports_dir/'run').exists())

    async def test_invalid_structure_and_missing_fields_are_rejected(self):
        for value in ('null', '{}', 'true', '"text"', '[1]', '[{}]',
                      json.dumps([{'title':'private-secret'}]),
                      json.dumps([dict(finding(), confidence='certain')]),
                      json.dumps([dict(finding(), query_ids='case-1')])):
            with self.subTest(value=value):
                result = await self.call(value)
                self.assertTrue(result.get('is_error'))
                self.assertFalse((self.ctx.reports_dir/'run').exists())

    async def test_each_required_finding_field_is_required_and_typed(self):
        for field in ('title','symptom','evidence','hypothesis','confidence','proposed_fix'):
            for missing in (True,False):
                value=finding()
                if missing: del value[field]
                else: value[field]=['private-secret']
                with self.subTest(field=field,missing=missing):
                    result=await self.call(json.dumps([value]))
                    self.assertTrue(result.get('is_error'))
                    self.assertNotIn('private-secret',result['content'][0]['text'])
                    self.assertFalse((self.ctx.reports_dir/'run').exists())

    async def test_unsupported_true_and_false_rejected_without_receipt(self):
        for claim in (True, False, 'false', 0):
            with self.subTest(claim=claim):
                result = await self.call(json.dumps([finding(verified=claim)]))
                self.assertTrue(result.get('is_error'))
                self.assertFalse((self.ctx.reports_dir/'run').exists())

    async def test_valid_empty_is_distinct_from_invalid(self):
        result = await self.call('[]')
        self.assertNotIn('is_error', result)
        payload = json.loads((self.ctx.reports_dir/'run/findings.json').read_text())
        self.assertEqual(payload['findings'], [])
        self.assertEqual(payload['schema_version'], 2)

    async def test_valid_populated_not_attempted(self):
        result = await self.call(json.dumps([finding(verified=None)]))
        self.assertNotIn('is_error', result)
        path = self.ctx.reports_dir/'run'
        self.assertIsNone(json.loads((path/'findings.json').read_text())['findings'][0]['verified'])
        self.assertIn('not attempted', (path/'report.md').read_text())

    def test_direct_writer_also_rejects_unreceipted_claim(self):
        rep = report.Report('run','synthetic',findings=[report.Finding(**finding(verified=True))])
        with self.assertRaises(ValueError):
            report.write(rep, self.ctx.reports_dir)
        self.assertFalse((self.ctx.reports_dir/'run').exists())

    def test_failed_second_staged_write_does_not_publish_partial(self):
        rep = report.Report('run','synthetic')
        original = Path.write_text
        def fail_json(path,*args,**kwargs):
            if path.name == 'findings.json': raise OSError('synthetic failure')
            return original(path,*args,**kwargs)
        with patch.object(Path,'write_text',fail_json), self.assertRaises(OSError):
            report.write(rep,self.ctx.reports_dir)
        self.assertFalse((self.ctx.reports_dir/'run').exists())

    async def test_existing_report_is_not_overwritten_on_invalid_or_repeat(self):
        await self.call('[]')
        path=self.ctx.reports_dir/'run'
        before={p.name:p.read_bytes() for p in path.iterdir()}
        self.assertTrue((await self.call('{'))['is_error'])
        self.assertTrue((await self.call('[]'))['is_error'])
        self.assertEqual(before,{p.name:p.read_bytes() for p in path.iterdir()})


if __name__=='__main__': unittest.main()


class ReportRunCompletionTests(unittest.IsolatedAsyncioTestCase):
    async def test_old_artifact_is_not_reported_as_current_success(self):
        from importlib import import_module
        mod=import_module('reelix_eval.agent.run')
        with TemporaryDirectory() as tmp:
            root=Path(tmp);old=root/'same-id';old.mkdir()
            (old/'report.md').write_text('historical artifact')
            cfg=mod.RunConfig(run_id='same-id',reports_dir=root)
            async def no_messages(**kwargs):
                if False: yield None
            with patch.object(mod,'preflight',return_value=[]), \
                 patch.object(mod,'build_options',return_value=object()), \
                 patch('reelix_eval.agent.stages.query',no_messages):
                result=await mod.run(cfg,engine=object(),llm_client=object())
            self.assertIsNone(result['report'])
            self.assertEqual((old/'report.md').read_text(),'historical artifact')
