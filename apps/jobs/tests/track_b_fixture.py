"""Closed, offline data boundary for Track B; contains no expected diagnoses.

A future MCP adapter may call `call`. It must expose no filesystem/shell/delegate
capabilities. This module never loads the separate reviewer oracle or credentials.
"""
import copy
import json
from pathlib import Path

PUBLIC = Path(__file__).parent / "fixtures" / "investigator_track_b"
SOURCE = "packages/python/reelix_agent/curator/curator_tiers.py"


class FixtureSession:
    def __init__(self, public_root=PUBLIC):
        data = json.loads((public_root / "observations.json").read_text())
        if data.get("synthetic") is not True:
            raise ValueError("Only synthetic inputs are accepted")
        self._windows = data["windows"]
        self._details = {d["query_id"]: d for d in data["details"]}
        self._source = json.loads((public_root / "source-context.json").read_text())["files"]
        if set(self._source) != {SOURCE}:
            raise ValueError("Unexpected source context")

    def call(self, name, args):
        if name == "list_eval_windows":
            result = {"windows": self._windows, "note": "Synthetic fixture, not production traffic."}
        elif name == "get_metrics":
            result = {"count": 0, "metrics": []}
        elif name == "compare_windows":
            result = {"source": "synthetic fixture", "deltas": [],
                      "sample_sizes": {"n_requests": {"baseline": 0, "current": 3}},
                      "caution": "No baseline cohort; no temporal movement can be established."}
        elif name == "sample_queries":
            if args.get("filter", "random") not in ("random", "low_fit", "no_match_heavy", "slow", "errored"):
                raise ValueError("Unknown filter")
            limit = args.get("limit", 3)
            if type(limit) is not int or not 1 <= limit <= 3:
                raise ValueError("Fixture samples are bounded to three")
            # A three-case diagnostic census, never an invented symptom ranking.
            ids = [] if args.get("filter") == "errored" else list(self._details)[:limit]
            result = {"count": len(ids),
                      "query_ids": ids, "eligible_population": 3,
                      "WARNING": "Synthetic census. Filter membership is not evidence of a symptom."}
        elif name == "get_query_detail":
            qid = args.get("query_id")
            if qid not in self._details:
                raise ValueError("Unknown fixture query ID")
            result = copy.deepcopy(self._details[qid])
            if args.get("served_only", True):
                result["candidates"] = [c for c in result["candidates"] if c["served"]]
        elif name == "get_source_excerpt":
            if args.get("path") != SOURCE:
                raise PermissionError("Only the frozen source snapshot is available")
            result = {"path": SOURCE, **self._source[SOURCE]}
        else:
            raise PermissionError("Tool is not available in the isolated fixture")
        return copy.deepcopy(result)
