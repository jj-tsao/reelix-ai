"""Read-only queries over the Reelix logging tables.

Every function takes an `Engine` and returns plain dataclasses — no LLM calls, no
mutation. This is the layer the Investigator's tools wrap.

All day boundaries are timezone-aware UTC. The logging tables store `timestamptz`,
so a naive datetime (or a bare `created_at::date` cast) is interpreted in the
server's timezone and silently shifts the boundary.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

QueryFilter = Literal["low_fit", "errored", "slow", "no_match_heavy", "random"]

#: Endpoints that run the full agent path (orchestrator → pipeline → curator).
AGENT_ENDPOINTS = ("discovery/explore", "mcp/explore")


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class Window:
    """One day of logged traffic, with the row counts that make it usable."""

    day: date
    traces: int
    errors: int
    curator_queries: int
    judged_queries: int

    @property
    def error_rate(self) -> float:
        return self.errors / self.traces if self.traces else 0.0


@dataclass
class MetricPoint:
    metric_date: date
    metric_name: str
    metric_group: str
    value: float | None
    details: dict | None = None


@dataclass
class MetricDelta:
    metric_name: str
    metric_group: str
    baseline: float | None
    current: float | None
    baseline_n: int
    current_n: int

    @property
    def absolute(self) -> float | None:
        if self.baseline is None or self.current is None:
            return None
        return self.current - self.baseline

    @property
    def relative(self) -> float | None:
        """Fractional change. None when the baseline is zero or missing."""
        if self.baseline is None or self.current is None or self.baseline == 0:
            return None
        return (self.current - self.baseline) / abs(self.baseline)


@dataclass
class CandidateDetail:
    media_id: int
    title: str
    genres: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    overview: str = ""
    release_year: int | None = None
    watch_providers: list[str] = field(default_factory=list)
    #: The compact card the curator actually reads ({id, t, g, k, o}). Frozen into
    #: eval sets so a replay reproduces the exact prompt the curator saw.
    llm_context: dict | None = None
    # Curator
    genre_fit: int | None = None
    tone_fit: int | None = None
    theme_fit: int | None = None
    total_fit: int | None = None
    tier: str | None = None
    is_served: bool = False
    final_rank: int | None = None
    # Pipeline
    score_dense: float | None = None
    score_sparse: float | None = None
    score_final: float | None = None
    # Explanation agent
    why_summary: str | None = None


@dataclass
class QueryDetail:
    query_id: str
    query_text: str
    spec_json: dict | None
    endpoint: str | None
    created_at: datetime | None
    candidates: list[CandidateDetail]
    # Trace
    status: str | None = None
    error_stage: str | None = None
    total_ms: int | None = None
    orchestrator_ms: int | None = None
    pipeline_ms: int | None = None
    curator_ms: int | None = None
    llm_calls: int | None = None
    total_input_tokens: int | None = None
    total_output_tokens: int | None = None
    # Tiers
    tier_stats: dict | None = None

    @property
    def served(self) -> list[CandidateDetail]:
        return [c for c in self.candidates if c.is_served]


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def day_bounds(target: date) -> tuple[datetime, datetime]:
    """(start_of_day_utc, start_of_next_day_utc) — timezone-aware."""
    start = datetime(target.year, target.month, target.day, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def range_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """Half-open [start, end) in UTC. `end` is exclusive at day granularity."""
    lo = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    hi = datetime(end.year, end.month, end.day, tzinfo=timezone.utc)
    return lo, hi


def parse_since(spec: str, today: date | None = None) -> tuple[date, date]:
    """Turn a `7d` / `2w` / `2026-07-01` window spec into a [start, end) pair.

    `end` is tomorrow, so today's partial data is included.
    """
    today = today or datetime.now(timezone.utc).date()
    end = today + timedelta(days=1)

    spec = spec.strip().lower()
    if spec.endswith("d") and spec[:-1].isdigit():
        return end - timedelta(days=int(spec[:-1])), end
    if spec.endswith("w") and spec[:-1].isdigit():
        return end - timedelta(weeks=int(spec[:-1])), end
    return date.fromisoformat(spec), end


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------

def list_windows(engine: Engine, days: int = 30) -> list[Window]:
    """Days with logged traffic, newest first, with the counts that gate analysis.

    A day with traces but zero `curator_queries` can't support curator analysis;
    zero `judged_queries` means the judge hasn't run for it yet.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)

    with engine.connect() as conn:
        trace_rows = conn.execute(
            text("""
                SELECT (created_at AT TIME ZONE 'UTC')::date AS day,
                       COUNT(*) AS traces,
                       COUNT(*) FILTER (WHERE status = 'error') AS errors
                FROM request_traces
                WHERE created_at >= :since
                GROUP BY 1
                ORDER BY 1 DESC
            """),
            {"since": since},
        ).fetchall()

        curator_rows = conn.execute(
            text("""
                SELECT (created_at AT TIME ZONE 'UTC')::date AS day,
                       COUNT(DISTINCT query_id) AS n
                FROM curator_evaluations
                WHERE created_at >= :since
                GROUP BY 1
            """),
            {"since": since},
        ).fetchall()

        judge_rows = conn.execute(
            text("""
                SELECT (created_at AT TIME ZONE 'UTC')::date AS day,
                       COUNT(DISTINCT query_id) AS n
                FROM judge_evaluations
                WHERE created_at >= :since
                GROUP BY 1
            """),
            {"since": since},
        ).fetchall()

    curator_by_day = {r.day: r.n for r in curator_rows}
    judge_by_day = {r.day: r.n for r in judge_rows}

    return [
        Window(
            day=r.day,
            traces=r.traces,
            errors=r.errors,
            curator_queries=curator_by_day.get(r.day, 0),
            judged_queries=judge_by_day.get(r.day, 0),
        )
        for r in trace_rows
    ]


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def get_metrics(
    engine: Engine,
    start: date,
    end: date,
    groups: list[str] | None = None,
) -> list[MetricPoint]:
    """`daily_metrics` rows for [start, end), optionally filtered to metric groups."""
    sql = """
        SELECT metric_date, metric_name, metric_group, value, details
        FROM daily_metrics
        WHERE metric_date >= :start AND metric_date < :end
    """
    params: dict[str, Any] = {"start": start, "end": end}
    if groups:
        sql += " AND metric_group = ANY(:groups)"
        params["groups"] = list(groups)
    sql += " ORDER BY metric_date, metric_group, metric_name"

    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).fetchall()

    return [
        MetricPoint(
            metric_date=r.metric_date,
            metric_name=r.metric_name,
            metric_group=r.metric_group,
            value=r.value,
            details=r.details,
        )
        for r in rows
    ]


def compare_windows(
    engine: Engine,
    baseline: tuple[date, date],
    current: tuple[date, date],
    groups: list[str] | None = None,
) -> list[MetricDelta]:
    """Mean metric value per window, with per-window sample sizes.

    Sample size is the number of days contributing to each mean — the caller
    needs it to tell a real movement from a one-day blip. A metric present in
    only one window still comes back, with `None` on the missing side.
    """
    base_points = get_metrics(engine, baseline[0], baseline[1], groups)
    curr_points = get_metrics(engine, current[0], current[1], groups)

    def _agg(points: list[MetricPoint]) -> dict[str, tuple[float | None, int, str]]:
        acc: dict[str, list[float]] = {}
        group_of: dict[str, str] = {}
        for p in points:
            group_of[p.metric_name] = p.metric_group
            if p.value is not None:
                acc.setdefault(p.metric_name, []).append(p.value)
        out: dict[str, tuple[float | None, int, str]] = {}
        for name, group in group_of.items():
            vals = acc.get(name, [])
            mean = sum(vals) / len(vals) if vals else None
            out[name] = (mean, len(vals), group)
        return out

    base_agg = _agg(base_points)
    curr_agg = _agg(curr_points)

    deltas: list[MetricDelta] = []
    for name in sorted(set(base_agg) | set(curr_agg)):
        b_val, b_n, b_group = base_agg.get(name, (None, 0, ""))
        c_val, c_n, c_group = curr_agg.get(name, (None, 0, ""))
        deltas.append(
            MetricDelta(
                metric_name=name,
                metric_group=c_group or b_group,
                baseline=b_val,
                current=c_val,
                baseline_n=b_n,
                current_n=c_n,
            )
        )
    return deltas


#: Metrics computed live from the logging tables, with the direction that counts
#: as "worse" — used to label a delta rather than leaving the reader to guess.
LIVE_METRIC_DIRECTION: dict[str, str] = {
    "error_rate": "lower_better",
    "total_ms_p50": "lower_better",
    "total_ms_p95": "lower_better",
    "curator_ms_p50": "lower_better",
    "pipeline_ms_p50": "lower_better",
    "avg_total_tokens": "lower_better",
    "avg_llm_calls": "lower_better",
    "mean_strong_count": "higher_better",
    "mean_no_match_count": "lower_better",
    "mean_served_count": "higher_better",
    "mean_total_fit": "higher_better",
    "recs_share": "neutral",
    "judge_relevance": "higher_better",
    "judge_novelty": "higher_better",
    "judge_explanation_quality": "higher_better",
    "judge_spec_fidelity": "higher_better",
    "judge_list_coherence": "higher_better",
}


def compute_window_metrics(engine: Engine, start: date, end: date) -> dict[str, Any]:
    """Aggregate the logging tables directly for [start, end).

    `daily_metrics` is only populated when the `eval_metrics` batch job runs, and
    it may be stale or empty for the window under investigation. Computing live
    means a comparison works on any window without depending on a job having run.
    Returns metric values plus the sample sizes needed to judge them.
    """
    lo, hi = range_bounds(start, end)
    params = {"start": lo, "end": hi}
    out: dict[str, Any] = {}

    with engine.connect() as conn:
        t = conn.execute(
            text("""
                SELECT COUNT(*) AS n,
                       COUNT(*) FILTER (WHERE status = 'error') AS errors,
                       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY total_ms) AS p50,
                       PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY total_ms) AS p95,
                       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY curator_ms) AS cur_p50,
                       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY pipeline_ms) AS pipe_p50,
                       AVG(COALESCE(total_input_tokens,0) + COALESCE(total_output_tokens,0))
                           AS avg_tokens,
                       AVG(llm_calls) AS avg_calls
                FROM request_traces
                WHERE created_at >= :start AND created_at < :end
            """),
            params,
        ).fetchone()

        out["n_requests"] = t.n or 0
        if t.n:
            out["error_rate"] = (t.errors or 0) / t.n
            out["total_ms_p50"] = t.p50
            out["total_ms_p95"] = t.p95
            out["curator_ms_p50"] = t.cur_p50
            out["pipeline_ms_p50"] = t.pipe_p50
            out["avg_total_tokens"] = float(t.avg_tokens) if t.avg_tokens else None
            out["avg_llm_calls"] = float(t.avg_calls) if t.avg_calls else None

        stages = conn.execute(
            text("""
                SELECT error_stage, COUNT(*) AS n FROM request_traces
                WHERE created_at >= :start AND created_at < :end AND status = 'error'
                GROUP BY 1 ORDER BY 2 DESC
            """),
            params,
        ).fetchall()
        out["errors_by_stage"] = {r.error_stage or "unknown": r.n for r in stages}

        tier = conn.execute(
            text("""
                SELECT COUNT(*) AS n,
                       AVG(strong_count) AS strong, AVG(moderate_count) AS moderate,
                       AVG(no_match_count) AS no_match, AVG(served_count) AS served
                FROM tier_summaries
                WHERE created_at >= :start AND created_at < :end
            """),
            params,
        ).fetchone()
        out["n_curated"] = tier.n or 0
        if tier.n:
            out["mean_strong_count"] = float(tier.strong) if tier.strong else None
            out["mean_moderate_count"] = float(tier.moderate) if tier.moderate else None
            out["mean_no_match_count"] = float(tier.no_match) if tier.no_match else None
            out["mean_served_count"] = float(tier.served) if tier.served else None

        fit = conn.execute(
            text("""
                SELECT AVG(total_fit) AS f, COUNT(*) AS n FROM curator_evaluations
                WHERE created_at >= :start AND created_at < :end AND is_served = true
            """),
            params,
        ).fetchone()
        out["n_served_candidates"] = fit.n or 0
        if fit.n:
            out["mean_total_fit"] = float(fit.f) if fit.f else None

        mode = conn.execute(
            text("""
                SELECT mode, COUNT(*) AS n FROM agent_decisions
                WHERE created_at >= :start AND created_at < :end
                GROUP BY 1
            """),
            params,
        ).fetchall()
        modes = {r.mode: r.n for r in mode}
        total_modes = sum(modes.values())
        out["n_decisions"] = total_modes
        if total_modes:
            out["recs_share"] = modes.get("RECS", 0) / total_modes

        judged = conn.execute(
            text("""
                SELECT COUNT(*) AS n, AVG(relevance) AS rel, AVG(novelty) AS nov,
                       AVG(explanation_quality) AS expl
                FROM judge_evaluations
                WHERE created_at >= :start AND created_at < :end
            """),
            params,
        ).fetchone()
        out["n_judged_items"] = judged.n or 0
        if judged.n:
            out["judge_relevance"] = float(judged.rel) if judged.rel else None
            out["judge_novelty"] = float(judged.nov) if judged.nov else None
            out["judge_explanation_quality"] = float(judged.expl) if judged.expl else None

        jq = conn.execute(
            text("""
                SELECT COUNT(*) AS n, AVG(spec_fidelity) AS sf, AVG(list_coherence) AS lc
                FROM judge_query_evaluations
                WHERE created_at >= :start AND created_at < :end AND status = 'ok'
            """),
            params,
        ).fetchone()
        out["n_judged_queries"] = jq.n or 0
        if jq.n:
            out["judge_spec_fidelity"] = float(jq.sf) if jq.sf else None
            out["judge_list_coherence"] = float(jq.lc) if jq.lc else None

    return out


def compare_windows_live(
    engine: Engine,
    baseline: tuple[date, date],
    current: tuple[date, date],
) -> tuple[list[MetricDelta], dict[str, Any]]:
    """Compare two windows using live aggregates. Returns (deltas, sample sizes)."""
    b = compute_window_metrics(engine, *baseline)
    c = compute_window_metrics(engine, *current)

    counts = {
        k: {"baseline": b.get(k, 0), "current": c.get(k, 0)}
        for k in (
            "n_requests",
            "n_curated",
            "n_served_candidates",
            "n_decisions",
            "n_judged_items",
            "n_judged_queries",
        )
    }

    deltas = [
        MetricDelta(
            metric_name=name,
            metric_group=LIVE_METRIC_DIRECTION.get(name, "neutral"),
            baseline=b.get(name),
            current=c.get(name),
            baseline_n=b.get("n_requests", 0),
            current_n=c.get("n_requests", 0),
        )
        for name in LIVE_METRIC_DIRECTION
        if b.get(name) is not None or c.get(name) is not None
    ]
    return deltas, {"counts": counts, "errors_by_stage": {
        "baseline": b.get("errors_by_stage", {}),
        "current": c.get("errors_by_stage", {}),
    }}


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------

#: Restricts a sample to queries `get_query_detail` can actually assemble.
#: `discovery/for-you` is a personalized feed with no text query, so all 358 of
#: its rows carry a NULL `query_text` — sampling them would hand the agent IDs
#: that silently resolve to nothing.
_HAS_TEXT = """
          AND EXISTS (
              SELECT 1 FROM rec_queries rq
              WHERE rq.query_id = {alias}.query_id AND rq.query_text IS NOT NULL
          )
"""

_FILTER_SQL: dict[str, str] = {
    # Served slate scored poorly by the curator itself.
    "low_fit": """
        SELECT rt.query_id
        FROM request_traces rt
        JOIN (
            SELECT query_id, AVG(total_fit) AS avg_fit
            FROM curator_evaluations
            WHERE is_served = true
            GROUP BY query_id
        ) ce ON ce.query_id = rt.query_id
        WHERE rt.created_at >= :start AND rt.created_at < :end
          AND rt.status = 'completed'
          AND ce.avg_fit IS NOT NULL
    """
    + _HAS_TEXT.format(alias="rt")
    + """
        ORDER BY ce.avg_fit ASC
        LIMIT :limit
    """,
    # Deliberately unfiltered: a request that died before intake logging has no
    # `rec_queries` row at all, and those are exactly the ones worth seeing. IDs
    # from this filter may not resolve to a full `get_query_detail`.
    "errored": """
        SELECT query_id
        FROM request_traces
        WHERE created_at >= :start AND created_at < :end
          AND status = 'error'
        ORDER BY created_at DESC
        LIMIT :limit
    """,
    "slow": """
        SELECT query_id
        FROM request_traces rt
        WHERE created_at >= :start AND created_at < :end
          AND status = 'completed' AND total_ms IS NOT NULL
    """
    + _HAS_TEXT.format(alias="rt")
    + """
        ORDER BY total_ms DESC
        LIMIT :limit
    """,
    # Retrieval surfaced little the curator could use.
    "no_match_heavy": """
        SELECT ts.query_id
        FROM tier_summaries ts
        WHERE ts.created_at >= :start AND ts.created_at < :end
          AND ts.total_candidates > 0
    """
    + _HAS_TEXT.format(alias="ts")
    + """
        ORDER BY ts.no_match_count::float / ts.total_candidates DESC
        LIMIT :limit
    """,
    "random": """
        SELECT query_id FROM (
            SELECT DISTINCT rt.query_id
            FROM request_traces rt
            WHERE rt.created_at >= :start AND rt.created_at < :end
              AND rt.status = 'completed'
              AND rt.curator_ms IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM curator_evaluations ce
                  WHERE ce.query_id = rt.query_id AND ce.is_served = true
              )
    """
    + _HAS_TEXT.format(alias="rt")
    + """
        ) sub
        ORDER BY RANDOM()
        LIMIT :limit
    """,
}


def sample_queries(
    engine: Engine,
    start: date,
    end: date,
    limit: int = 20,
    query_filter: QueryFilter = "random",
) -> list[str]:
    """Query IDs in [start, end) matching a symptom filter."""
    sql = _FILTER_SQL.get(query_filter)
    if sql is None:
        raise ValueError(
            f"Unknown filter {query_filter!r}; expected one of {sorted(_FILTER_SQL)}"
        )

    lo, hi = range_bounds(start, end)
    with engine.connect() as conn:
        rows = conn.execute(text(sql), {"start": lo, "end": hi, "limit": limit}).fetchall()

    ids = [r.query_id for r in rows]
    logger.info("sample_queries(%s) → %d ids", query_filter, len(ids))
    return ids


# ---------------------------------------------------------------------------
# Query detail
# ---------------------------------------------------------------------------

def get_query_detail(
    engine: Engine,
    query_id: str,
    backfill_payloads: bool = True,
    served_only: bool = True,
) -> QueryDetail | None:
    """Assemble everything known about one query.

    Joins `rec_queries` (text), `agent_decisions` (spec), `curator_evaluations`
    (fits/tiers), `rec_results` (pipeline scores + why text), `request_traces`
    (timings) and `tier_summaries`.

    `backfill_payloads` fetches genres/keywords/overview from Qdrant by media_id.
    The logging tables never stored them, so without this the judge sees only a
    title — the bug that made the original judge's "judge on metadata" prompt a
    lie. Set False to avoid the Qdrant dependency.
    """
    with engine.connect() as conn:
        q_row = conn.execute(
            text("""
                SELECT query_text, endpoint, created_at
                FROM rec_queries
                WHERE query_id = :qid
                ORDER BY created_at DESC
                LIMIT 1
            """),
            {"qid": query_id},
        ).fetchone()

        if not q_row or not q_row.query_text:
            return None

        spec_row = conn.execute(
            text("""
                SELECT spec_json FROM agent_decisions
                WHERE query_id = :qid AND mode = 'RECS'
                ORDER BY created_at DESC LIMIT 1
            """),
            {"qid": query_id},
        ).fetchone()

        trace_row = conn.execute(
            text("""
                SELECT status, error_stage, total_ms, orchestrator_ms, pipeline_ms,
                       curator_ms, llm_calls, total_input_tokens, total_output_tokens
                FROM request_traces
                WHERE query_id = :qid
                ORDER BY created_at DESC LIMIT 1
            """),
            {"qid": query_id},
        ).fetchone()

        tier_row = conn.execute(
            text("""
                SELECT total_candidates, strong_count, moderate_count, no_match_count,
                       served_count, selection_rule
                FROM tier_summaries
                WHERE query_id = :qid LIMIT 1
            """),
            {"qid": query_id},
        ).fetchone()

        # Restrict to the LATEST curator run for this query_id.
        #
        # `/explore/rerun` reuses the same query_id, so a query can have several
        # runs. Since 2026-08-01 the logger upserts on (query_id, media_id) and
        # stamps one fresh `created_at` per run, so a rerun updates in place and
        # candidates it drops keep their older timestamp — matching
        # max(created_at) therefore isolates exactly the slate the user last saw.
        #
        # This also repairs history: before that fix the table had no unique
        # index and reruns appended, leaving 21 queries with 2-9 stacked runs.
        # Taking the newest row *per media_id* instead of the newest *run* would
        # splice those together into a 17-title "served slate" for a query that
        # only ever served 8, and the judge would mark it down for duplicates
        # that exist only in the log.
        #
        # DISTINCT ON is a belt-and-braces guard in case one run ever writes a
        # candidate twice. The outer sort is pipeline-rank order, NOT served-first:
        # `apply_curator_tiers` preserves the incoming order within each tier, so
        # replaying a reordered list changes which candidates get served even when
        # every fit score matches.
        served_clause = "AND ce.is_served = true" if served_only else ""
        cand_sql = f"""
            SELECT * FROM (
                SELECT DISTINCT ON (ce.media_id)
                       ce.media_id, ce.title, ce.created_at,
                       ce.genre_fit, ce.tone_fit, ce.theme_fit, ce.total_fit,
                       ce.tier, ce.is_served, ce.final_rank,
                       rr.rank AS pipeline_rank,
                       rr.score_dense, rr.score_sparse, rr.score_final,
                       rr.why_summary
                FROM curator_evaluations ce
                LEFT JOIN rec_results rr
                    ON ce.query_id = rr.query_id AND ce.media_id = rr.media_id
                WHERE ce.query_id = :qid {served_clause}
                  AND ce.created_at = (
                      SELECT MAX(created_at) FROM curator_evaluations
                      WHERE query_id = :qid
                  )
                ORDER BY ce.media_id, ce.created_at DESC
            ) d
            ORDER BY d.pipeline_rank NULLS LAST, d.final_rank NULLS LAST, d.media_id
        """

        cand_rows = conn.execute(text(cand_sql), {"qid": query_id}).fetchall()

    if not cand_rows:
        return None

    candidates = [
        CandidateDetail(
            media_id=r.media_id,
            title=r.title or f"ID:{r.media_id}",
            genre_fit=r.genre_fit,
            tone_fit=r.tone_fit,
            theme_fit=r.theme_fit,
            total_fit=r.total_fit,
            tier=r.tier,
            is_served=bool(r.is_served),
            final_rank=r.final_rank,
            score_dense=r.score_dense,
            score_sparse=r.score_sparse,
            score_final=r.score_final,
            why_summary=r.why_summary,
        )
        for r in cand_rows
    ]

    if backfill_payloads:
        _backfill_from_qdrant(candidates)

    return QueryDetail(
        query_id=query_id,
        query_text=q_row.query_text,
        spec_json=spec_row.spec_json if spec_row else None,
        endpoint=q_row.endpoint,
        created_at=q_row.created_at,
        candidates=candidates,
        status=trace_row.status if trace_row else None,
        error_stage=trace_row.error_stage if trace_row else None,
        total_ms=trace_row.total_ms if trace_row else None,
        orchestrator_ms=trace_row.orchestrator_ms if trace_row else None,
        pipeline_ms=trace_row.pipeline_ms if trace_row else None,
        curator_ms=trace_row.curator_ms if trace_row else None,
        llm_calls=trace_row.llm_calls if trace_row else None,
        total_input_tokens=trace_row.total_input_tokens if trace_row else None,
        total_output_tokens=trace_row.total_output_tokens if trace_row else None,
        tier_stats=dict(tier_row._mapping) if tier_row else None,
    )


def _backfill_from_qdrant(candidates: list[CandidateDetail]) -> None:
    """Fill genres/keywords/overview/year/providers in place, by media_id.

    Best-effort: a Qdrant outage degrades the judge to title-only rather than
    failing the run. Imported lazily so `store` stays importable without
    qdrant-client installed.
    """
    if not candidates:
        return

    try:
        import os

        from qdrant_client import QdrantClient
        from reelix_core.config import QDRANT_MOVIE_COLLECTION_NAME
    except ImportError as e:
        logger.warning("Qdrant backfill unavailable (%s) — judging on titles only", e)
        return

    try:
        client = QdrantClient(
            url=os.getenv("QDRANT_ENDPOINT"),
            api_key=os.getenv("QDRANT_API_KEY"),
            timeout=30,
        )
        points = client.retrieve(
            collection_name=QDRANT_MOVIE_COLLECTION_NAME,
            ids=[c.media_id for c in candidates],
            with_payload=True,
            with_vectors=False,
        )
    except Exception as e:
        logger.warning("Qdrant backfill failed (%s) — judging on titles only", e)
        return

    by_id = {int(p.id): (p.payload or {}) for p in points}
    for c in candidates:
        p = by_id.get(c.media_id)
        if not p:
            continue
        c.genres = p.get("genres") or []
        c.keywords = (p.get("keywords") or [])[:8]
        c.overview = p.get("overview") or ""
        c.release_year = p.get("release_year")
        c.watch_providers = p.get("watch_providers") or []
        c.llm_context = p.get("llm_context")
        if not c.title or c.title.startswith("ID:"):
            c.title = p.get("title") or c.title

    logger.debug("Backfilled %d/%d candidates from Qdrant", len(by_id), len(candidates))