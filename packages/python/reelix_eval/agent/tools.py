"""In-process MCP tools — thin wrappers over the Phase 1 library.

Each tool runs inside *this* Python process (not the SDK's `claude` subprocess),
so anything a tool calls is billed to whatever credential that code uses. That is
deliberate for `run_judge`: it calls the Messages API with
`REELIX_JUDGE_ANTHROPIC_KEY`, keeping the judge's spend separate and its schema
guarantee intact, while the agent's own turns run under the Claude Code login.

Tools resolve to the agent as `mcp__reelix_eval__<name>`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date
from pathlib import Path
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from reelix_eval import store
from reelix_eval.judge import JudgeConfig, build_client, judge_queries
from reelix_eval.judge import runner as judge_runner
from reelix_eval.replay import evalset as evalset_mod
from reelix_eval.replay import curator as replay_mod

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[4]


# ---------------------------------------------------------------------------
# Tool context
# ---------------------------------------------------------------------------

@dataclass
class ToolContext:
    """Everything the tools need, injected once by `run.py`.

    Held module-level because the `@tool` decorator hands the handler only its
    arguments — there is no per-call context parameter.
    """

    engine: Any
    llm_client: Any = None
    judge_cfg: JudgeConfig = field(default_factory=JudgeConfig)
    evalsets_dir: Path = REPO_ROOT / "apps/data-pipeline/evalsets"
    reports_dir: Path = REPO_ROOT / "apps/data-pipeline/reports"
    run_id: str = "adhoc"
    apply_mode: bool = False
    #: Replay runs produced this session, keyed by label, so `score_replay` can
    #: pick up what `replay_curator` produced without re-running the LLM.
    replays: dict[str, replay_mod.ReplayRun] = field(default_factory=dict)
    #: Findings the agent has recorded, in order, for `write_report`.
    judge_cache: dict[str, Any] = field(default_factory=dict)


_ctx: ToolContext | None = None


def configure(ctx: ToolContext) -> None:
    global _ctx
    _ctx = ctx


def _require_ctx() -> ToolContext:
    if _ctx is None:
        raise RuntimeError("reelix_eval.agent.tools.configure() was never called")
    return _ctx


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _json_default(o: Any) -> Any:
    if is_dataclass(o) and not isinstance(o, type):
        return asdict(o)
    if isinstance(o, (date,)):
        return o.isoformat()
    if isinstance(o, Path):
        return str(o)
    return str(o)


def _ok(payload: Any) -> dict:
    return {
        "content": [
            {"type": "text", "text": json.dumps(payload, default=_json_default, indent=2)}
        ]
    }


def _err(message: str) -> dict:
    return {"content": [{"type": "text", "text": message}], "is_error": True}


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _ids(value: Any) -> list[str]:
    """Accept a list or a comma-separated string of query IDs."""
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return [str(v) for v in (value or [])]


# ---------------------------------------------------------------------------
# Read tools
# ---------------------------------------------------------------------------

@tool(
    "list_eval_windows",
    "List days that have logged traffic, with the row counts that gate analysis "
    "(traces, errors, queries with curator data, queries already judged). Start "
    "here to find out which windows can actually support a comparison.",
    {"days": int},
)
async def list_eval_windows(args: dict[str, Any]) -> dict:
    ctx = _require_ctx()
    windows = store.list_windows(ctx.engine, days=int(args.get("days") or 30))
    return _ok(
        {
            "windows": [
                {
                    "day": w.day.isoformat(),
                    "traces": w.traces,
                    "errors": w.errors,
                    "error_rate": round(w.error_rate, 4),
                    "curator_queries": w.curator_queries,
                    "judged_queries": w.judged_queries,
                }
                for w in windows
            ],
            "note": (
                "A day with traces but curator_queries=0 cannot support curator "
                "analysis. judged_queries=0 means the judge has not run for it."
            ),
        }
    )


@tool(
    "get_metrics",
    "Read daily_metrics rows for a date range [start, end). Optionally filter to "
    "metric groups (cost, latency, curator, errors, routing, judge). Dates are "
    "ISO (YYYY-MM-DD); end is exclusive.",
    {"start": str, "end": str, "groups": str},
)
async def get_metrics(args: dict[str, Any]) -> dict:
    ctx = _require_ctx()
    groups = [g.strip() for g in (args.get("groups") or "").split(",") if g.strip()]
    points = store.get_metrics(
        ctx.engine, _parse_date(args["start"]), _parse_date(args["end"]), groups or None
    )
    return _ok(
        {
            "count": len(points),
            "metrics": [
                {
                    "date": p.metric_date.isoformat(),
                    "name": p.metric_name,
                    "group": p.metric_group,
                    "value": p.value,
                    "details": p.details,
                }
                for p in points
            ],
        }
    )


@tool(
    "compare_windows",
    "Compare mean metric values between a baseline window and a current window. "
    "Returns absolute and relative deltas WITH per-window sample sizes — a large "
    "relative move on one or two days is noise, not a finding.",
    {
        "baseline_start": str,
        "baseline_end": str,
        "current_start": str,
        "current_end": str,
        "groups": str,
    },
)
async def compare_windows(args: dict[str, Any]) -> dict:
    ctx = _require_ctx()
    groups = [g.strip() for g in (args.get("groups") or "").split(",") if g.strip()]
    baseline = (_parse_date(args["baseline_start"]), _parse_date(args["baseline_end"]))
    current = (_parse_date(args["current_start"]), _parse_date(args["current_end"]))

    # Computed live from the logging tables rather than read from daily_metrics:
    # that table is only written when the eval_metrics batch job runs, and it is
    # currently populated for a single day in March. Live aggregation means a
    # comparison works on any window without depending on a job having run.
    deltas, context = store.compare_windows_live(ctx.engine, baseline, current)

    # daily_metrics still carries the batch history where it exists.
    batch = store.compare_windows(ctx.engine, baseline, current, groups or None)

    return _ok(
        {
            "source": "computed live from logging tables",
            "sample_sizes": context["counts"],
            "errors_by_stage": context["errors_by_stage"],
            "deltas": [
                {
                    "metric": d.metric_name,
                    "direction": d.metric_group,
                    "baseline": d.baseline,
                    "current": d.current,
                    "absolute": d.absolute,
                    "relative": d.relative,
                    "baseline_requests": d.baseline_n,
                    "current_requests": d.current_n,
                }
                for d in deltas
            ],
            "batch_metrics_available": len(batch),
            "caution": (
                "request_traces has a series break on 2026-08-01: error_rate, "
                "llm_calls and token totals all step up because tool-level failures "
                "stopped being counted as successes and curator tokens started "
                "being summed. A comparison spanning that date will show phantom "
                "regressions on those metrics."
            ),
        }
    )


@tool(
    "sample_queries",
    "Sample query IDs matching a symptom filter: low_fit (curator scored its own "
    "picks poorly), errored, slow, no_match_heavy (retrieval surfaced little the "
    "curator could use), or random. Note that errored IDs may not resolve to a "
    "full detail — a request that died before intake logging has no query text.",
    {"start": str, "end": str, "limit": int, "filter": str},
)
async def sample_queries(args: dict[str, Any]) -> dict:
    ctx = _require_ctx()
    try:
        ids = store.sample_queries(
            ctx.engine,
            _parse_date(args["start"]),
            _parse_date(args["end"]),
            int(args.get("limit") or 20),
            args.get("filter") or "random",
        )
    except ValueError as e:
        return _err(str(e))
    return _ok({"count": len(ids), "query_ids": ids})


@tool(
    "get_query_detail",
    "Full assembled context for one query: user text, orchestrator spec, every "
    "candidate with its real metadata (backfilled from Qdrant), curator fits and "
    "tiers, pipeline scores, the served 'why' text, and trace timings.",
    {"query_id": str, "served_only": bool},
)
async def get_query_detail(args: dict[str, Any]) -> dict:
    ctx = _require_ctx()
    detail = store.get_query_detail(
        ctx.engine,
        args["query_id"],
        backfill_payloads=True,
        served_only=bool(args.get("served_only", True)),
    )
    if not detail:
        return _err(
            f"No detail for {args['query_id']} — no rec_queries row with query "
            "text, or no curator evaluations."
        )

    return _ok(
        {
            "query_id": detail.query_id,
            "query_text": detail.query_text,
            "spec": detail.spec_json,
            "endpoint": detail.endpoint,
            "trace": {
                "status": detail.status,
                "error_stage": detail.error_stage,
                "total_ms": detail.total_ms,
                "orchestrator_ms": detail.orchestrator_ms,
                "pipeline_ms": detail.pipeline_ms,
                "curator_ms": detail.curator_ms,
                "llm_calls": detail.llm_calls,
                "input_tokens": detail.total_input_tokens,
                "output_tokens": detail.total_output_tokens,
            },
            "tier_stats": detail.tier_stats,
            "candidates": [
                {
                    "media_id": c.media_id,
                    "title": c.title,
                    "year": c.release_year,
                    "genres": c.genres,
                    "keywords": c.keywords,
                    "curator": {
                        "genre_fit": c.genre_fit,
                        "tone_fit": c.tone_fit,
                        "theme_fit": c.theme_fit,
                        "total_fit": c.total_fit,
                        "tier": c.tier,
                    },
                    "served": c.is_served,
                    "rank": c.final_rank,
                    "score_final": c.score_final,
                    "why": c.why_summary,
                }
                for c in detail.candidates
            ],
        }
    )


# ---------------------------------------------------------------------------
# Judge
# ---------------------------------------------------------------------------

@tool(
    "run_judge",
    "Judge specific query IDs now and return per-item and aggregate scores. Use "
    "this to confirm that a metric movement is a genuine quality change rather "
    "than a shift in traffic mix. Costs roughly $0.04 per query.",
    {"query_ids": str, "persist": bool},
)
async def run_judge(args: dict[str, Any]) -> dict:
    ctx = _require_ctx()
    ids = _ids(args.get("query_ids"))
    if not ids:
        return _err("query_ids is required")

    details = [
        d
        for d in (store.get_query_detail(ctx.engine, q) for q in ids)
        if d is not None
    ]
    if not details:
        return _err("None of those query IDs resolved to judgeable detail.")

    client = build_client()
    judgements = await judge_queries(client, details, ctx.judge_cfg)

    if args.get("persist"):
        judge_runner.persist(ctx.engine, judgements, ctx.run_id, ctx.judge_cfg)

    for j in judgements:
        ctx.judge_cache[j.query_id] = j

    return _ok(
        {
            "summary": judge_runner.summarize(judgements, ctx.judge_cfg),
            "per_query": [
                {
                    "query_id": j.query_id,
                    "query_text": j.query_text,
                    "status": j.status,
                    "spec_fidelity": j.spec_fidelity,
                    "list_coherence": j.list_coherence,
                    "reasoning": j.query_reasoning,
                    "items": [
                        {
                            "title": i.title,
                            "relevance": i.relevance,
                            "novelty": i.novelty,
                            "explanation_quality": i.explanation_quality,
                            "grounded": i.explanation_grounded,
                            "spec_violation": i.spec_violation,
                            "spec_violation_code": i.spec_violation_code,
                            "curator_total_fit": i.curator_total_fit,
                            "curator_tier": i.curator_tier,
                            "reasoning": i.rec_reasoning,
                        }
                        for i in j.items
                    ],
                }
                for j in judgements
            ],
        }
    )


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------

@tool(
    "snapshot_evalset",
    "Freeze query IDs plus their retrieved candidates into a reproducible eval "
    "set on disk. Snapshot BEFORE editing anything, from traffic that predates "
    "the change, so the frozen baseline reflects real production behaviour.",
    {"query_ids": str, "name": str},
)
async def snapshot_evalset(args: dict[str, Any]) -> dict:
    ctx = _require_ctx()
    ids = _ids(args.get("query_ids"))
    if not ids:
        return _err("query_ids is required")

    path = evalset_mod.snapshot(
        ctx.engine, ids, args.get("name") or "default", ctx.evalsets_dir
    )
    cases = evalset_mod.load(path)
    return _ok(
        {
            "path": str(path),
            "requested": len(ids),
            "cases": len(cases),
            "skipped": len(ids) - len(cases),
            "candidates": sum(len(c.candidates) for c in cases),
        }
    )


@tool(
    "replay_curator",
    "Re-run the curator stage over a frozen eval set against the CURRENT working "
    "tree, then compare to the frozen baseline. This is what makes a prompt edit "
    "verifiable. An unchanged replay reproduces only ~0.80 served overlap and "
    "tier counts wander by ~0.25, so treat smaller movements as noise.",
    {"evalset": str, "label": str},
)
async def replay_curator(args: dict[str, Any]) -> dict:
    ctx = _require_ctx()
    if ctx.llm_client is None:
        return _err("No LLM client configured for replay.")

    path = evalset_mod.evalset_path(args.get("evalset") or "default", ctx.evalsets_dir)
    if not path.exists():
        return _err(f"Eval set not found: {path}. Run snapshot_evalset first.")

    cases = evalset_mod.load(path)
    label = args.get("label") or "working-tree"
    run = await replay_mod.replay(cases, ctx.llm_client, label=label)
    ctx.replays[label] = run

    return _ok(
        {
            "summary": run.summary(),
            "noise_floor": {
                "served_overlap_unchanged": 0.80,
                "tier_count_variation": 0.25,
                "measured": "20 cases, gpt-4.1-mini, temperature=0.1, 2026-08-01",
            },
            "per_case": [
                {
                    "query_id": c.query_id,
                    "ok": c.ok,
                    "error": c.error,
                    "served_overlap": c.served_overlap,
                    "tier_stats": c.tier_stats,
                }
                for c in run.cases
            ],
        }
    )


@tool(
    "score_replay",
    "Judge a replay's served slate and compare it against the frozen baseline "
    "slate, judged the same way. This is the A/B that tells you whether an edit "
    "actually improved anything. Report a regression plainly.",
    {"evalset": str, "label": str},
)
async def score_replay(args: dict[str, Any]) -> dict:
    ctx = _require_ctx()
    label = args.get("label") or "working-tree"
    run = ctx.replays.get(label)
    if run is None:
        return _err(f"No replay labelled {label!r}. Run replay_curator first.")

    path = evalset_mod.evalset_path(args.get("evalset") or "default", ctx.evalsets_dir)
    cases = {c.query_id: c for c in evalset_mod.load(path)}

    baseline_details, replay_details = [], []
    for case_replay in run.ok_cases:
        case = cases.get(case_replay.query_id)
        if not case:
            continue
        baseline_details.append(_detail_from_case(case, case.baseline_served_ids))
        replay_details.append(_detail_from_case(case, case_replay.served_ids))

    if not baseline_details:
        return _err("No successfully replayed cases to score.")

    client = build_client()
    base_j, new_j = await asyncio.gather(
        judge_queries(client, baseline_details, ctx.judge_cfg),
        judge_queries(client, replay_details, ctx.judge_cfg),
    )

    base_s = judge_runner.summarize(base_j, ctx.judge_cfg)
    new_s = judge_runner.summarize(new_j, ctx.judge_cfg)
    axes = (
        "avg_relevance",
        "avg_novelty",
        "avg_spec_fidelity",
        "avg_list_coherence",
        "spec_violation_rate_judge",
    )
    return _ok(
        {
            "cases": len(baseline_details),
            "ab": [
                {
                    "axis": a,
                    "baseline": base_s.get(a),
                    "replay": new_s.get(a),
                    "delta": (
                        None
                        if base_s.get(a) is None or new_s.get(a) is None
                        else round(new_s[a] - base_s[a], 4)
                    ),
                }
                for a in axes
            ],
            "tier_shift": {
                "baseline_strong": run.summary().get("baseline_mean_strong_count"),
                "replay_strong": run.summary().get("mean_strong_count"),
            },
            "caution": (
                "Explanation quality is not comparable here: replayed slates have "
                "no 'why' text, so only curator-side axes are meaningful. With a "
                "small eval set, a delta under ~0.3 on a 1-5 axis is within noise."
            ),
        }
    )


def _detail_from_case(case, served_ids: list[int]) -> store.QueryDetail:
    """Build a judgeable QueryDetail from a frozen case and a chosen slate."""
    by_id = {c.media_id: c for c in case.candidates}
    served = []
    for rank, mid in enumerate(served_ids, start=1):
        c = by_id.get(mid)
        if not c:
            continue
        served.append(
            store.CandidateDetail(
                media_id=c.media_id,
                title=c.title,
                genres=c.genres,
                keywords=c.keywords,
                overview=c.overview,
                release_year=c.release_year,
                watch_providers=c.watch_providers,
                llm_context=c.llm_context,
                total_fit=c.baseline_total_fit,
                tier=c.baseline_tier,
                is_served=True,
                final_rank=rank,
            )
        )
    return store.QueryDetail(
        query_id=case.query_id,
        query_text=case.query_text,
        spec_json=case.spec_json,
        endpoint=None,
        created_at=None,
        candidates=served,
    )


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

@tool(
    "write_report",
    """Write the run report (report.md + findings.json) and return its path.

Every argument except `window` is a JSON STRING. Fill every field of every
finding — do not put the whole analysis into `evidence`; the four fields are
rendered as separate sections and an empty one prints as an empty heading.

findings: [{
  "title":        one line, states the conclusion (not "Curator issue"),
  "symptom":      what is observably wrong, 1-2 sentences,
  "evidence":     the numbers and query IDs that establish it,
  "hypothesis":   why you think it happens (mechanism, not restatement),
  "confidence":   "high" | "medium" | "low",
  "proposed_fix": concrete change, as a ```diff block where possible,
  "location":     "path/to/file.py:LINE",
  "query_ids":    ["..."],
  "verified":     true/false/null  (null when no replay ran)
}]
health: [{"metric","group","baseline","current","verdict","baseline_n","current_n"}]
  — carry over what compare_windows returned, including flat metrics.
sample_sizes: {"judged_queries": N, "queries_read": N, ...}
verification: {"evalset","cases","cases_failed","rows":[{"name","baseline","current"}],"note"}
blind_spots: ["anything you could not reach this run"]

Rank findings most-significant first. Label weak evidence low-confidence rather
than dropping or inflating it. If nothing is wrong, pass an empty findings list.""",
    {
        "window": str,
        "baseline_window": str,
        "health": str,
        "findings": str,
        "verification": str,
        "blind_spots": str,
        "sample_sizes": str,
    },
)
async def write_report(args: dict[str, Any]) -> dict:
    from reelix_eval import report as report_mod

    ctx = _require_ctx()

    def _load(key: str, default):
        raw = args.get(key)
        if not raw:
            return default
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return default
        return raw

    findings_raw = _load("findings", [])
    health_raw = _load("health", [])

    rep = report_mod.Report(
        run_id=ctx.run_id,
        window=args.get("window") or "unspecified",
        baseline_window=args.get("baseline_window") or None,
        judge_model=ctx.judge_cfg.model,
        sample_sizes=_load("sample_sizes", {}),
        git_sha=report_mod.git_sha(REPO_ROOT),
        health=[
            report_mod.HealthRow(
                metric=h.get("metric", "?"),
                group=h.get("group", ""),
                baseline=h.get("baseline"),
                current=h.get("current"),
                verdict=h.get("verdict", ""),
                baseline_n=h.get("baseline_n", 0),
                current_n=h.get("current_n", 0),
            )
            for h in health_raw
        ],
        findings=[
            report_mod.Finding(
                title=f.get("title", "Untitled"),
                symptom=f.get("symptom", ""),
                evidence=f.get("evidence", ""),
                hypothesis=f.get("hypothesis", ""),
                confidence=f.get("confidence", "low"),
                proposed_fix=f.get("proposed_fix", ""),
                location=f.get("location"),
                query_ids=f.get("query_ids", []),
                verified=f.get("verified"),
                verification_note=f.get("verification_note"),
            )
            for f in findings_raw
        ],
        verification=_load("verification", None),
        extra_blind_spots=_load("blind_spots", []),
        applied_branch=ctx.judge_cache.get("_branch"),
    )

    path = report_mod.write(rep, ctx.reports_dir)

    # Surface incomplete findings so the agent can correct them in this run.
    # Left silent, a finding with everything crammed into `evidence` renders as
    # a series of empty headings and nobody notices until they read the file.
    incomplete = [
        {
            "title": f.title[:60],
            "missing": [
                name
                for name, value in (
                    ("symptom", f.symptom),
                    ("hypothesis", f.hypothesis),
                    ("proposed_fix", f.proposed_fix),
                    ("location", f.location),
                )
                if not (value or "").strip()
            ],
        }
        for f in rep.findings
    ]
    incomplete = [i for i in incomplete if i["missing"]]

    result: dict[str, Any] = {"report": str(path), "findings": len(rep.findings)}
    if incomplete:
        result["WARNING"] = (
            "These findings have empty fields that will render as empty sections. "
            "Call write_report again with them filled in."
        )
        result["incomplete"] = incomplete
    if not rep.health:
        result.setdefault("WARNING", "")
        result["health_missing"] = (
            "No health rows were passed, so the report says 'No metrics available' "
            "even though compare_windows returned data. Pass them."
        )
    return _ok(result)


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

ALL_TOOLS = [
    list_eval_windows,
    get_metrics,
    compare_windows,
    sample_queries,
    get_query_detail,
    run_judge,
    snapshot_evalset,
    replay_curator,
    score_replay,
    write_report,
]

#: Fully-qualified names, for `allowed_tools` and per-subagent tool lists.
TOOL_NAMES = [f"mcp__reelix_eval__{t.name}" for t in ALL_TOOLS]

READ_TOOL_NAMES = [
    f"mcp__reelix_eval__{n}"
    for n in (
        "list_eval_windows",
        "get_metrics",
        "compare_windows",
        "sample_queries",
        "get_query_detail",
    )
]
REPLAY_TOOL_NAMES = [
    f"mcp__reelix_eval__{n}"
    for n in ("snapshot_evalset", "replay_curator", "score_replay", "run_judge")
]


def build_server():
    """The in-process MCP server exposing every eval tool."""
    return create_sdk_mcp_server(name="reelix_eval", tools=ALL_TOOLS)