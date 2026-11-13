"""Model-free consistency tests for the public synthetic inputs, not diagnosis tests.

The reviewer oracle is deliberately not imported or required by this test suite.
"""
import hashlib
import json
import unittest
from pathlib import Path

from reelix_agent.curator.curator_tiers import apply_curator_tiers
from reelix_ranking.types import Candidate

FIXTURES = Path(__file__).parent / "fixtures" / "investigator_track_b"
REPO = Path(__file__).resolve().parents[3]


class TrackBFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads((FIXTURES / "observations.json").read_text())
        cls.cases = {d["query_id"]: d for d in cls.fixture["details"]}

    def test_public_inputs_are_synthetic_unique_and_unlabelled(self):
        self.assertTrue(self.fixture["synthetic"])
        self.assertEqual(len(self.cases), 3)
        self.assertTrue(all(q.startswith("fixture-") for q in self.cases))
        self.assertEqual(self.fixture["windows"][0]["traces"], 3)
        def walk(value):
            if isinstance(value, dict):
                for k, v in value.items():
                    self.assertNotIn(k, {"oracle", "expected_stage", "expected_detection", "role"})
                    walk(v)
            elif isinstance(value, list):
                for v in value:
                    walk(v)
        walk(self.fixture)

    def check_tiering(self, query_id, raw_evaluations):
        case = self.cases[query_id]
        candidates = [Candidate(id=c["media_id"], payload={"title": c["title"]})
                      for c in case["candidates"]]
        served, stats = apply_curator_tiers(
            evaluation_results=raw_evaluations, candidates=candidates, limit=2,
        )
        self.assertEqual([c.id for c in served],
                         [c["media_id"] for c in case["candidates"] if c["served"]])
        for observed, computed in zip(case["candidates"], candidates):
            self.assertEqual(observed["curator"]["tier"], computed.payload["curator_category"])
            self.assertEqual(observed["curator"]["total_fit"], computed.payload["curator_total_fit"])
        self.assertEqual(stats["served_count"], case["tier_stats"]["served_count"])

    def test_literal_omission_reproduces_public_served_zero_fit(self):
        # Deliberately return no evaluation for the second candidate. Expected
        # observations were fixed before any model execution or self-assessment.
        self.check_tiering("fixture-e791", [
            {"media_id": 910000001, "genre_fit": 2, "tone_fit": 2, "theme_fit": 2},
        ])
        c = self.cases["fixture-e791"]["candidates"][1]
        self.assertTrue(c["served"])
        self.assertEqual(c["curator"]["total_fit"], 0)
        self.assertEqual(c["curator"]["tier"], "moderate_match")

    def test_fully_scored_control_excludes_zero_fit_candidate(self):
        self.check_tiering("fixture-c284", [
            {"media_id": 910000001, "genre_fit": 2, "tone_fit": 2, "theme_fit": 2},
            {"media_id": 910000002, "genre_fit": 0, "tone_fit": 0, "theme_fit": 0},
        ])
        self.assertFalse(self.cases["fixture-c284"]["candidates"][1]["served"])

    def test_missing_evidence_is_missing_not_fabricated_healthy_data(self):
        d = self.cases["fixture-b615"]
        self.assertIsNone(d["spec"])
        self.assertIsNone(d["tier_stats"])
        self.assertIsNone(d["trace"]["curator_ms"])
        self.assertEqual(d["candidates"][0]["genres"], [])
        self.assertTrue(all(v is None for v in d["candidates"][0]["curator"].values()))

    def test_source_context_is_frozen_real_code_without_arbitrary_files(self):
        context = json.loads((FIXTURES / "source-context.json").read_text())
        path = "packages/python/reelix_agent/curator/curator_tiers.py"
        self.assertEqual(set(context["files"]), {path})
        snap = context["files"][path]
        self.assertEqual(hashlib.sha256(snap["text"].encode()).hexdigest(), snap["sha256"])
        self.assertEqual(hashlib.sha256((REPO / path).read_bytes()).hexdigest(), snap["sha256"])


class TrackBIsolationTests(unittest.TestCase):
    def setUp(self):
        from track_b_fixture import FixtureSession
        self.session = FixtureSession()

    def test_no_production_judge_replay_or_file_tools(self):
        for name in ("run_judge", "snapshot_evalset", "replay_curator", "score_replay",
                     "Read", "Grep", "Glob", "Bash", "Agent", "Task", "execute_sql"):
            with self.subTest(name=name), self.assertRaises(PermissionError):
                self.session.call(name, {"persist": True, "path": "oracle.json"})

    def test_oracle_cannot_be_read_as_source_or_query(self):
        for path in ("oracle.json", "../../reports/oracle.json", "/private/tmp/oracle.json"):
            with self.subTest(path=path):
                with self.assertRaises(PermissionError):
                    self.session.call("get_source_excerpt", {"path": path})
                with self.assertRaises(ValueError):
                    self.session.call("get_query_detail", {"query_id": path})

    def test_fixture_census_is_bounded_and_not_a_symptom_label(self):
        result = self.session.call("sample_queries", {"filter": "low_fit", "limit": 3})
        self.assertEqual(result["count"], 3)
        self.assertIn("not evidence", result["WARNING"])
        self.assertEqual(self.session.call("sample_queries", {"filter": "errored"})["count"], 0)
        for limit in (0, 4, "3", True):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                self.session.call("sample_queries", {"limit": limit})

    def test_supported_source_and_detail_have_no_fallback(self):
        from track_b_fixture import SOURCE
        self.assertIn("text", self.session.call("get_source_excerpt", {"path": SOURCE}))
        details = self.session.call("get_query_detail", {"query_id": "fixture-c284", "served_only": False})
        self.assertEqual(len(details["candidates"]), 2)
        self.assertEqual(len(self.session.call("get_query_detail", {"query_id": "fixture-c284"})["candidates"]), 1)

    def test_returned_data_cannot_mutate_later_observations(self):
        result = self.session.call("get_query_detail", {"query_id": "fixture-c284"})
        result["spec"]["exclude_genres"].clear()
        again = self.session.call("get_query_detail", {"query_id": "fixture-c284"})
        self.assertEqual(again["spec"]["exclude_genres"], ["Horror"])


if __name__ == "__main__":
    unittest.main()
