"""
Automated evaluation metrics for Reelix agent logging.

Queries the logging tables (request_traces, tier_summaries, curator_evaluations,
agent_decisions, rec_results) and computes daily metrics for monitoring
recommendation quality, latency, cost, and reliability.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


@dataclass
class MetricRow:
    metric_date: date
    metric_name: str
    metric_group: str
    value: float | None = None
    details: dict | None = None


def _date_bounds(target_date: date) -> tuple[datetime, datetime]:
    """Return (start_of_day_utc, start_of_next_day_utc) for SQL filtering."""
    start = datetime(target_date.year, target_date.month, target_date.day)
    end = start + timedelta(days=1)
    return start, end


# ---------------------------------------------------------------------------
# Curator metrics
# ---------------------------------------------------------------------------

def compute_curator_metrics(engine: Engine, target_date: date) -> list[MetricRow]:
    start, end = _date_bounds(target_date)
    rows: list[MetricRow] = []

    with engine.connect() as conn:
        # Tier distribution from tier_summaries
        tier_row = conn.execute(
            text("""
                SELECT
                    COUNT(*) AS n,
                    AVG(strong_count::float / NULLIF(total_candidates, 0)) AS strong_rate,
                    AVG(moderate_count::float / NULLIF(total_candidates, 0)) AS moderate_rate,
                    AVG(no_match_count::float / NULLIF(total_candidates, 0)) AS no_match_rate,
                    AVG(served_count::float / NULLIF(total_candidates, 0)) AS served_ratio
                FROM tier_summaries
                WHERE created_at >= :start AND created_at < :end
            """),
            {"start": start, "end": end},
        ).fetchone()

        if tier_row and tier_row.n > 0:
            rows.append(MetricRow(target_date, "strong_match_rate", "curator", tier_row.strong_rate))
            rows.append(MetricRow(target_date, "moderate_match_rate", "curator", tier_row.moderate_rate))
            rows.append(MetricRow(target_date, "no_match_rate", "curator", tier_row.no_match_rate))
            rows.append(MetricRow(target_date, "served_ratio", "curator", tier_row.served_ratio))

        # Selection rule distribution
        rule_rows = conn.execute(
            text("""
                SELECT selection_rule, COUNT(*) AS cnt
                FROM tier_summaries
                WHERE created_at >= :start AND created_at < :end
                GROUP BY selection_rule
            """),
            {"start": start, "end": end},
        ).fetchall()

        if rule_rows:
            dist = {r.selection_rule: r.cnt for r in rule_rows}
            total = sum(dist.values())
            rows.append(MetricRow(target_date, "selection_rule_distribution", "curator", total, dist))

        # Average fit score for served candidates
        fit_row = conn.execute(
            text("""
                SELECT AVG(total_fit) AS avg_fit
                FROM curator_evaluations
                WHERE created_at >= :start AND created_at < :end
                  AND is_served = true
            """),
            {"start": start, "end": end},
        ).fetchone()

        if fit_row and fit_row.avg_fit is not None:
            rows.append(MetricRow(target_date, "fit_score_avg", "curator", float(fit_row.avg_fit)))

        # Curator fit vs pipeline score correlation
        corr_row = conn.execute(
            text("""
                SELECT CORR(ce.total_fit, rr.score_final) AS correlation
                FROM curator_evaluations ce
                JOIN rec_results rr
                  ON ce.query_id = rr.query_id AND ce.media_id = rr.media_id
                WHERE ce.created_at >= :start AND ce.created_at < :end
            """),
            {"start": start, "end": end},
        ).fetchone()

        if corr_row and corr_row.correlation is not None:
            rows.append(MetricRow(target_date, "fit_pipeline_correlation", "curator", float(corr_row.correlation)))

    return rows


# ---------------------------------------------------------------------------
# Latency metrics
# ---------------------------------------------------------------------------

def compute_latency_metrics(engine: Engine, target_date: date) -> list[MetricRow]:
    start, end = _date_bounds(target_date)
    rows: list[MetricRow] = []

    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT
                    COUNT(*) AS n,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY total_ms) AS total_p50,
                    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY total_ms) AS total_p95,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY orchestrator_ms) AS orch_p50,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY pipeline_ms) AS pipeline_p50,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY curator_ms) AS curator_p50,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY reflection_ms) AS reflection_p50
                FROM request_traces
                WHERE created_at >= :start AND created_at < :end
                  AND status = 'completed'
            """),
            {"start": start, "end": end},
        ).fetchone()

        if result and result.n > 0:
            rows.append(MetricRow(target_date, "total_ms_p50", "latency", result.total_p50))
            rows.append(MetricRow(target_date, "total_ms_p95", "latency", result.total_p95))
            if result.orch_p50 is not None:
                rows.append(MetricRow(target_date, "orchestrator_ms_p50", "latency", result.orch_p50))
            if result.pipeline_p50 is not None:
                rows.append(MetricRow(target_date, "pipeline_ms_p50", "latency", result.pipeline_p50))
            if result.curator_p50 is not None:
                rows.append(MetricRow(target_date, "curator_ms_p50", "latency", result.curator_p50))
            if result.reflection_p50 is not None:
                rows.append(MetricRow(target_date, "reflection_ms_p50", "latency", result.reflection_p50))

    return rows


# ---------------------------------------------------------------------------
# Cost metrics
# ---------------------------------------------------------------------------

def compute_cost_metrics(engine: Engine, target_date: date) -> list[MetricRow]:
    start, end = _date_bounds(target_date)
    rows: list[MetricRow] = []

    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT
                    COUNT(*) AS request_count,
                    COALESCE(SUM(total_input_tokens), 0) AS sum_input,
                    COALESCE(SUM(total_output_tokens), 0) AS sum_output,
                    AVG(COALESCE(total_input_tokens, 0) + COALESCE(total_output_tokens, 0)) AS avg_tokens
                FROM request_traces
                WHERE created_at >= :start AND created_at < :end
            """),
            {"start": start, "end": end},
        ).fetchone()

        if result and result.request_count > 0:
            rows.append(MetricRow(target_date, "request_count", "cost", result.request_count))
            rows.append(MetricRow(target_date, "total_input_tokens", "cost", result.sum_input))
            rows.append(MetricRow(target_date, "total_output_tokens", "cost", result.sum_output))
            rows.append(MetricRow(target_date, "avg_tokens_per_query", "cost", result.avg_tokens))

    return rows


# ---------------------------------------------------------------------------
# Error metrics
# ---------------------------------------------------------------------------

def compute_error_metrics(engine: Engine, target_date: date) -> list[MetricRow]:
    start, end = _date_bounds(target_date)
    rows: list[MetricRow] = []

    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE status = 'error') AS errors
                FROM request_traces
                WHERE created_at >= :start AND created_at < :end
            """),
            {"start": start, "end": end},
        ).fetchone()

        if result and result.total > 0:
            rate = result.errors / result.total
            rows.append(MetricRow(target_date, "error_rate", "errors", rate))

            # Breakdown by stage
            if result.errors > 0:
                stage_rows = conn.execute(
                    text("""
                        SELECT error_stage, COUNT(*) AS cnt
                        FROM request_traces
                        WHERE created_at >= :start AND created_at < :end
                          AND status = 'error'
                        GROUP BY error_stage
                    """),
                    {"start": start, "end": end},
                ).fetchall()

                breakdown = {r.error_stage or "unknown": r.cnt for r in stage_rows}
                rows.append(MetricRow(target_date, "error_count_by_stage", "errors", result.errors, breakdown))

    return rows


# ---------------------------------------------------------------------------
# Routing metrics
# ---------------------------------------------------------------------------

def compute_routing_metrics(engine: Engine, target_date: date) -> list[MetricRow]:
    start, end = _date_bounds(target_date)
    rows: list[MetricRow] = []

    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE mode = 'CHAT') AS chat_count,
                    COUNT(*) FILTER (WHERE mode = 'RECS') AS recs_count
                FROM agent_decisions
                WHERE created_at >= :start AND created_at < :end
            """),
            {"start": start, "end": end},
        ).fetchone()

        if result and result.total > 0:
            rows.append(MetricRow(target_date, "chat_rate", "routing", result.chat_count / result.total))
            rows.append(MetricRow(target_date, "recs_rate", "routing", result.recs_count / result.total))

    return rows


# ---------------------------------------------------------------------------
# Judge metrics (from judge_evaluations, if eval_judge has run)
# ---------------------------------------------------------------------------

def compute_judge_metrics(engine: Engine, target_date: date) -> list[MetricRow]:
    start, end = _date_bounds(target_date)
    rows: list[MetricRow] = []

    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT
                    COUNT(DISTINCT query_id) AS sample_size,
                    AVG(relevance) AS avg_relevance,
                    AVG(novelty) AS avg_novelty,
                    AVG(explanation_quality) AS avg_expl_quality
                FROM judge_evaluations
                WHERE created_at >= :start AND created_at < :end
            """),
            {"start": start, "end": end},
        ).fetchone()

        if result and result.sample_size and result.sample_size > 0:
            rows.append(MetricRow(target_date, "judge_sample_size", "judge", result.sample_size))
            if result.avg_relevance is not None:
                rows.append(MetricRow(target_date, "judge_avg_relevance", "judge", float(result.avg_relevance)))
            if result.avg_novelty is not None:
                rows.append(MetricRow(target_date, "judge_avg_novelty", "judge", float(result.avg_novelty)))
            if result.avg_expl_quality is not None:
                rows.append(MetricRow(target_date, "judge_avg_explanation_quality", "judge", float(result.avg_expl_quality)))

            # Judge-curator correlation
            corr_row = conn.execute(
                text("""
                    SELECT CORR(relevance, curator_total_fit) AS correlation
                    FROM judge_evaluations
                    WHERE created_at >= :start AND created_at < :end
                      AND relevance IS NOT NULL AND curator_total_fit IS NOT NULL
                """),
                {"start": start, "end": end},
            ).fetchone()

            if corr_row and corr_row.correlation is not None:
                rows.append(MetricRow(target_date, "judge_curator_correlation", "judge", float(corr_row.correlation)))

    return rows


# ---------------------------------------------------------------------------
# Aggregation + persistence
# ---------------------------------------------------------------------------

def compute_all_metrics(engine: Engine, target_date: date) -> list[MetricRow]:
    """Run all metric queries for a single date."""
    all_rows: list[MetricRow] = []
    for compute_fn in (
        compute_curator_metrics,
        compute_latency_metrics,
        compute_cost_metrics,
        compute_error_metrics,
        compute_routing_metrics,
        compute_judge_metrics,
    ):
        try:
            all_rows.extend(compute_fn(engine, target_date))
        except Exception:
            logger.exception("Failed computing %s for %s", compute_fn.__name__, target_date)
    return all_rows


def upsert_metrics(engine: Engine, metrics: list[MetricRow]) -> None:
    """Upsert computed metrics into daily_metrics table."""
    if not metrics:
        return

    with engine.begin() as conn:
        for m in metrics:
            conn.execute(
                text("""
                    INSERT INTO daily_metrics (metric_date, metric_name, metric_group, value, details)
                    VALUES (:metric_date, :metric_name, :metric_group, :value, :details)
                    ON CONFLICT (metric_date, metric_name)
                    DO UPDATE SET value = EXCLUDED.value,
                                  details = EXCLUDED.details,
                                  created_at = now()
                """),
                {
                    "metric_date": m.metric_date,
                    "metric_name": m.metric_name,
                    "metric_group": m.metric_group,
                    "value": m.value,
                    "details": json.dumps(m.details) if m.details else None,
                },
            )

    logger.info("Upserted %d metrics for %s", len(metrics), metrics[0].metric_date if metrics else "?")


def print_summary(metrics: list[MetricRow]) -> None:
    """Print a formatted summary of computed metrics to stdout."""
    if not metrics:
        logger.info("No metrics computed (no data for this date).")
        return

    target_date = metrics[0].metric_date
    print(f"\n{'=' * 60}")
    print(f"  Reelix Daily Metrics — {target_date}")
    print(f"{'=' * 60}")

    groups: dict[str, list[MetricRow]] = {}
    for m in metrics:
        groups.setdefault(m.metric_group, []).append(m)

    for group_name in ("cost", "latency", "curator", "errors", "routing", "judge"):
        group_metrics = groups.get(group_name, [])
        if not group_metrics:
            continue

        print(f"\n  [{group_name.upper()}]")
        for m in group_metrics:
            if m.value is None:
                continue

            if m.metric_name.endswith("_rate") or m.metric_name.endswith("_ratio"):
                val_str = f"{m.value:.1%}"
            elif m.metric_name.endswith("_p50") or m.metric_name.endswith("_p95"):
                val_str = f"{m.value:.0f} ms"
            elif m.metric_name.endswith("_tokens") or m.metric_name == "request_count":
                val_str = f"{int(m.value):,}"
            elif m.metric_name == "avg_tokens_per_query":
                val_str = f"{m.value:,.0f}"
            elif m.metric_name in ("fit_pipeline_correlation", "judge_curator_correlation"):
                val_str = f"{m.value:.3f}"
            elif m.metric_name == "fit_score_avg":
                val_str = f"{m.value:.2f}"
            elif m.metric_name.startswith("judge_avg_"):
                val_str = f"{m.value:.1f} / 5"
            elif m.metric_name == "judge_sample_size":
                val_str = f"{int(m.value)} queries"
            else:
                val_str = f"{m.value}"

            label = m.metric_name.replace("_", " ").title()
            print(f"    {label:<35} {val_str}")

            if m.details:
                for k, v in m.details.items():
                    print(f"      - {k}: {v}")

    print(f"\n{'=' * 60}\n")
