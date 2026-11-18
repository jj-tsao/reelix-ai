"""SDK boundary tests with fake streams and host-observed synthetic tool data."""
import asyncio
from dataclasses import asdict
from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from claude_agent_sdk import PermissionResultDeny, ResultMessage
from reelix_eval.agent import stages, tools
from reelix_eval.agent.run import RunConfig, check_bash, run
from reelix_eval.case import CaseIdentity, InvestigationCase
from reelix_eval.orchestration import AssessmentSubmission, StageRequest
from reelix_eval.replay.isolated import source_manifest, manifest_digest
from reelix_eval.report import Finding
from reelix_eval.trust import Policy, TrustedContext, digest


class SDKTests(unittest.IsolatedAsyncioTestCase):
    def setup_adapter(self):
        root = Path(self.enterContext(TemporaryDirectory()))
        revision = manifest_digest(source_manifest(tools.REPO_ROOT / 'packages/python'))
        self.ctx = TrustedContext(case_id='sdk', query_ids=('q',), current_revision=revision)
        self.cfg = RunConfig(run_id='sdk', reports_dir=root, apply_mode=True)
        self.case = InvestigationCase(CaseIdentity('sdk', 'synthetic', 'frozen', ('q',), revision, Policy().revision), root / 'cases')
        self.adapter = stages.ClaudeStageExecutor(self.cfg, self.case, self.ctx, windows=((date(2026, 1, 1), date(2026, 1, 3)),))
        self.request = StageRequest('investigation', 'sdk', '{}', 3, 1., AssessmentSubmission)
        return self.adapter

    async def test_actual_options_exclude_publication_replay_and_all_write_capabilities(self):
        adapter = self.setup_adapter()
        options = adapter.build_options(self.request)
        names = {t.name for t in adapter.server_tools}
        self.assertNotIn('write_report', names)
        self.assertFalse({'replay_curator', 'score_replay', 'run_judge', 'snapshot_evalset'} & names)
        self.assertFalse({'Bash', 'Edit', 'Write', 'Read'} & set(options.allowed_tools))
        self.assertEqual(options.max_turns, 3)
        self.assertEqual(options.setting_sources, [])
        self.assertEqual(set(options.agents), {'metrics-analyst', 'query-inspector'})
        self.assertEqual(options.output_format['schema'], AssessmentSubmission.model_json_schema())
        for name in ('Bash', 'Edit', 'Write', 'mcp__reelix_eval__write_report', 'mcp__reelix_eval__assess_trust'):
            self.assertIsInstance(await options.can_use_tool(name, {}, None), PermissionResultDeny)
        self.assertIsInstance(check_bash('git checkout -b unsafe', True), PermissionResultDeny)

    async def test_scoped_tools_register_only_host_observed_payload(self):
        adapter = self.setup_adapter()
        detail_tool = next(t for t in adapter.server_tools if t.name == 'get_query_detail')
        with patch.object(tools.get_query_detail, 'handler', AsyncMock(return_value=tools._ok({'query_id': 'q', 'fit': 0}))) as observed:
            denied = await detail_tool.handler({'query_id': 'foreign'})
            self.assertTrue(denied['is_error'])
            observed.assert_not_awaited()
            accepted = await detail_tool.handler({'query_id': 'q'})
        payload = json.loads(accepted['content'][0]['text'])
        evidence = self.ctx.evidence.resolve(payload['evidence_id'])
        self.assertEqual(evidence.case_id, 'sdk')
        self.assertEqual(evidence.query_ids, ('q',))
        self.assertEqual(evidence.payload()['fit'], 0)
        self.assertTrue(any(e.kind == 'evidence_registered' for e in self.case.history))
        for name, args in (('get_metrics', {'start': '2025-01-01', 'end': '2025-01-02'}),
                           ('compare_windows', {'baseline_start': '2025-01-01', 'baseline_end': '2025-01-02'})):
            tool = next(t for t in adapter.server_tools if t.name == name)
            self.assertTrue((await tool.handler(args))['is_error'])

    async def test_scoped_source_and_binding_reject_authority(self):
        adapter = self.setup_adapter()
        source = next(t for t in adapter.server_tools if t.name == 'read_case_source')
        self.assertTrue((await source.handler({'path': '/etc/passwd'}))['is_error'])
        self.assertTrue((await source.handler({'path': '.env'}))['is_error'])
        result = await source.handler({'path': 'packages/python/reelix_agent/curator/curator_tiers.py'})
        payload = json.loads(result['content'][0]['text'])
        self.assertEqual(self.ctx.evidence.resolve(payload['evidence_id']).kind, 'source')
        bind = next(t for t in adapter.server_tools if t.name == 'bind_case_finding')
        finding = asdict(Finding('Synthetic', 'fit', 'q', 'hypothesis', 'low', '', query_ids=['q']))
        accepted = await bind.handler({'finding_json': json.dumps(finding)})
        self.assertEqual(json.loads(accepted['content'][0]['text'])['finding_sha256'], digest(finding))
        finding['verified'] = True
        self.assertTrue((await bind.handler({'finding_json': json.dumps(finding)}))['is_error'])
        self.assertEqual(self.ctx.findings, {})
        self.ctx.current_revision = 'stale'
        with self.assertRaises(ValueError):
            adapter._check_sources()

    async def test_terminal_results_are_validated_and_metrics_recorded(self):
        adapter = self.setup_adapter()
        for mode in ('empty', 'error', 'no_output', 'valid', 'terminated_after_output'):
            async def stream(**kwargs):
                if mode == 'empty':
                    return
                yield ResultMessage('success' if mode != 'error' else 'error_max_turns', 1, 1,
                    mode == 'error', 2, 'fake-session', total_cost_usd=.0,
                    structured_output={'synthetic': True} if mode in ('valid', 'terminated_after_output') else None)
                if mode == 'terminated_after_output':
                    raise RuntimeError('transport failed')
            with patch.object(stages, 'query', stream):
                if mode == 'valid':
                    self.assertEqual(await adapter(self.request), {'synthetic': True})
                else:
                    with self.assertRaises((ValueError, RuntimeError)):
                        await adapter(self.request)
        self.assertTrue(any(e.kind == 'sdk_result' for e in self.case.history))

    async def test_apply_rejected_before_any_sdk_or_database_access(self):
        self.setup_adapter()
        with patch.object(stages, 'query') as query, self.assertRaises(RuntimeError):
            await run(self.cfg, engine=object())
        query.assert_not_called()

    async def test_default_run_uses_host_assurance_and_publication_with_fake_sdk(self):
        root = Path(self.enterContext(TemporaryDirectory()))
        cfg = RunConfig(run_id='integrated', reports_dir=root)
        captured = {}
        original = stages.ClaudeStageExecutor._build_tools
        def capture_tools(executor):
            items = original(executor)
            captured['executor'] = executor
            return items
        async def stream(**kwargs):
            task = None
            async for message in kwargs['prompt']:
                task = json.loads(message['message']['content'])
            context = task['context']
            executor = captured['executor']
            runtime = next(t for t in executor.server_tools if t.name == 'get_query_detail')
            observed = await runtime.handler({'query_id': 'q'})
            evidence_id = json.loads(observed['content'][0]['text'])['evidence_id']
            yield ResultMessage('success', 1, 1, False, 1, 'fake-session', total_cost_usd=0., structured_output={
                'case_id': 'integrated', 'policy_revision': Policy().revision,
                'source_revision': context['source_revision'], 'finding': None,
                'assessment': {'outcome': 'clean', 'finding_id': 'clean', 'finding_sha256': digest({'outcome': 'clean'}),
                    'observations': [{'evidence_id': evidence_id, 'pointer': '/fit', 'expected_json': '0', 'description': 'Synthetic measurement'}]}})
        with patch('reelix_eval.agent.run.preflight', return_value=[]), \
             patch('reelix_eval.store.incident_query_ids', return_value=['q']), \
             patch.object(tools.get_query_detail, 'handler', AsyncMock(return_value=tools._ok({'query_id': 'q', 'fit': 0}))), \
             patch.object(stages.ClaudeStageExecutor, '_build_tools', capture_tools), \
             patch.object(stages, 'query', stream):
            result = await run(cfg, engine=object())
        self.assertEqual(result['status'], 'completed')
        case = json.loads(Path(result['report']).with_name('findings.json').read_text())['investigation_case']
        self.assertTrue(any(e['kind'] == 'assurance' for e in case['history']))
        self.assertTrue(any(e['kind'] == 'sdk_result' for e in case['history']))
        self.assertEqual(case['status'], 'completed')
