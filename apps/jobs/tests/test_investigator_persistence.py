"""Authorization regressions; all model/telemetry calls and DB connections are fake.

Run from apps/jobs: .venv/bin/python -m unittest discover -s tests -v
"""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

from reelix_eval import judge
from reelix_eval.agent import tools
from reelix_eval.judge import runner
from reelix_eval.replay.curator import CaseReplay, ReplayRun
from reelix_eval.replay.evalset import EvalCase, FrozenCandidate
from reelix_eval.store import QueryDetail


class InvestigatorPersistenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = self.enterContext(TemporaryDirectory())
        self.engine = MagicMock(name="no_real_database")
        self.ctx = tools.ToolContext(
            engine=self.engine, evalsets_dir=Path(tmp), reports_dir=Path(tmp),
            run_id="synthetic-test", apply_mode=False,
        )
        self.enterContext(patch.object(tools, "_ctx", self.ctx))
        detail = QueryDetail("case", "Synthetic request", None, None, None, [])
        self.details = self.enterContext(
            patch.object(tools.store, "get_query_detail", return_value=detail)
        )
        self.client = self.enterContext(patch.object(tools, "build_client"))
        self.judgement = runner.QueryJudgement(
            query_id="case", query_text="Synthetic request",
            items=[runner.ItemJudgement("case", 1, "Synthetic title", "Synthetic request")],
        )
        self.generate = self.enterContext(patch.object(
            tools, "judge_queries", new=AsyncMock(return_value=[self.judgement])
        ))

    def assert_no_io(self):
        self.details.assert_not_called()
        self.client.assert_not_called()
        self.generate.assert_not_awaited()
        self.engine.begin.assert_not_called()
        self.assertEqual(self.ctx.judge_cache, {})

    async def test_read_only_persistence_denied_before_any_io(self):
        result = await tools.run_judge.handler({"query_ids": "case", "persist": True})
        self.assertTrue(result["is_error"])
        self.assertIn("persistence is disabled", result["content"][0]["text"])
        self.assert_no_io()

    async def test_request_cannot_override_execution_authorization(self):
        result = await tools.run_judge.handler({
            "query_ids": "case", "persist": True, "apply_mode": True,
        })
        self.assertTrue(result["is_error"])
        self.assert_no_io()

    async def test_apply_authorization_is_required_even_if_config_is_enabled(self):
        self.ctx.judge_cfg.persist = True
        result = await tools.run_judge.handler({"query_ids": "case", "persist": True})
        self.assertTrue(result["is_error"])
        self.assert_no_io()

    async def test_truthy_non_boolean_request_cannot_bypass_denial(self):
        for value in ("true", "false", 1, {"enabled": True}):
            with self.subTest(value=value):
                result = await tools.run_judge.handler({"query_ids": "case", "persist": value})
                self.assertTrue(result["is_error"])
        self.assert_no_io()

    async def test_nonpersisting_judging_allowed_in_both_modes(self):
        for apply_mode in (False, True):
            for args in ({"query_ids": "case"}, {"query_ids": "case", "persist": False}):
                with self.subTest(apply_mode=apply_mode, args=args):
                    ctx = tools.ToolContext(
                        self.engine, self.ctx.evalsets_dir, self.ctx.reports_dir,
                        apply_mode=apply_mode,
                    )
                    with patch.object(tools, "_ctx", ctx):
                        result = await tools.run_judge.handler(args)
                    self.assertNotIn("is_error", result)
                    self.assertEqual(json.loads(result["content"][0]["text"])["summary"]["queries"], 1)
                    self.assertIs(ctx.judge_cache["case"], self.judgement)
        self.engine.begin.assert_not_called()

    async def test_apply_mode_explicit_persistence_writes_query_and_item(self):
        ctx = tools.ToolContext(
            self.engine, self.ctx.evalsets_dir, self.ctx.reports_dir, apply_mode=True,
        )
        with patch.object(tools, "_ctx", ctx):
            result = await tools.run_judge.handler({"query_ids": "case", "persist": True})
        self.assertNotIn("is_error", result)
        self.engine.begin.assert_called_once()
        writes = self.engine.begin.return_value.__enter__.return_value.execute.call_args_list
        self.assertEqual(len(writes), 2)
        self.assertIn("INSERT INTO judge_query_evaluations", str(writes[0].args[0]))
        self.assertIn("INSERT INTO judge_evaluations", str(writes[1].args[0]))

    async def test_disabled_config_denies_even_in_apply_mode(self):
        ctx = tools.ToolContext(
            self.engine, self.ctx.evalsets_dir, self.ctx.reports_dir,
            apply_mode=True, judge_cfg=runner.JudgeConfig(persist=False),
        )
        with patch.object(tools, "_ctx", ctx):
            result = await tools.run_judge.handler({"query_ids": "case", "persist": True})
        self.assertTrue(result["is_error"])
        self.assert_no_io()

    def test_read_only_context_copies_and_disables_shared_config(self):
        shared = runner.JudgeConfig(persist=True, max_tokens=1234)
        ctx = tools.ToolContext(
            self.engine, self.ctx.evalsets_dir, self.ctx.reports_dir,
            apply_mode=False, judge_cfg=shared,
        )
        self.assertFalse(ctx.judge_cfg.persist)
        self.assertTrue(shared.persist)  # standalone jobs retain their own policy
        self.assertEqual(ctx.judge_cfg.max_tokens, 1234)

    def test_direct_shared_persistence_paths_honor_read_only_policy(self):
        for persist in (runner.persist, judge.persist):
            for records in ([], [self.judgement]):
                with self.subTest(persist=persist, empty=not records):
                    with self.assertRaises(PermissionError):
                        persist(self.engine, records, "synthetic", self.ctx.judge_cfg)
        self.engine.begin.assert_not_called()

    def test_standalone_default_persistence_remains_allowed(self):
        judge.persist(self.engine, [self.judgement], "standalone-test")
        self.engine.begin.assert_called_once()
        self.assertEqual(
            self.engine.begin.return_value.__enter__.return_value.execute.call_count, 2,
        )

    async def test_score_replay_does_not_implicitly_persist_in_either_mode(self):
        case = EvalCase("case", "Synthetic request", {}, [
            FrozenCandidate(1, "Synthetic title", {"t": "Synthetic title"}),
        ], baseline_served_ids=[1])
        for apply_mode in (False, True):
            with self.subTest(apply_mode=apply_mode):
                ctx = tools.ToolContext(
                    self.engine, self.ctx.evalsets_dir, self.ctx.reports_dir,
                    apply_mode=apply_mode,
                )
                ctx.replays["test"] = ReplayRun("test", [
                    CaseReplay("case", "Synthetic request", served_ids=[1]),
                ])
                with patch.object(tools, "_ctx", ctx), \
                     patch.object(tools.evalset_mod, "load", return_value=[case]), \
                     patch.object(runner, "persist", side_effect=AssertionError("Unexpected write")):
                    result = await tools.score_replay.handler({"label": "test"})
                self.assertNotIn("is_error", result)
        self.engine.begin.assert_not_called()


if __name__ == "__main__":
    unittest.main()
