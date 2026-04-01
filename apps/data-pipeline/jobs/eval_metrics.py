"""
Automated evaluation metrics job for Reelix agent logging.

Computes daily metrics from logging tables (request_traces, tier_summaries,
curator_evaluations, agent_decisions, rec_results) and persists them to
the daily_metrics table.

Usage:
    python -m jobs.eval_metrics                       # yesterday (default)
    python -m jobs.eval_metrics --date 2026-03-30     # specific date
    python -m jobs.eval_metrics --days 7              # last 7 days (backfill)
"""

import argparse
import logging
from datetime import date, timedelta

from core.config import DATABASE_URL
from core.db import get_engine
from core.metrics_queries import compute_all_metrics, print_summary, upsert_metrics

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def _validate_env():
    if not DATABASE_URL:
        raise EnvironmentError("Missing required env var: DATABASE_URL")


def main():
    parser = argparse.ArgumentParser(
        description="Compute daily evaluation metrics from Reelix logging tables."
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Target date (YYYY-MM-DD). Defaults to yesterday.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=1,
        help="Number of days to compute (counting back from --date). Default: 1.",
    )
    args = parser.parse_args()
    _validate_env()

    # Resolve date range
    if args.date:
        end_date = date.fromisoformat(args.date)
    else:
        end_date = date.today() - timedelta(days=1)

    dates = [end_date - timedelta(days=i) for i in range(args.days)]
    dates.reverse()  # oldest first

    logger.info("=" * 60)
    logger.info("Reelix eval_metrics job")
    logger.info("Date range: %s to %s (%d day(s))", dates[0], dates[-1], len(dates))
    logger.info("=" * 60)

    engine = get_engine()

    for target_date in dates:
        logger.info("Computing metrics for %s ...", target_date)
        metrics = compute_all_metrics(engine, target_date)

        if metrics:
            upsert_metrics(engine, metrics)
            print_summary(metrics)
        else:
            logger.info("No data found for %s — skipping.", target_date)

    logger.info("Done.")


if __name__ == "__main__":
    main()
