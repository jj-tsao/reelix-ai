"""
LLM-as-judge evaluation job for Reelix recommendations.

Samples completed agent queries for a date and scores them with two independent
Claude calls per query — recommendation quality judged WITHOUT the "why" text,
explanation quality WITH it — so curator and explanation-agent quality stay
separable. Results land in `judge_evaluations` (per candidate) and
`judge_query_evaluations` (per query; token counts live here only).

The implementation moved to `packages/python/reelix_eval/judge/`; this file is
the CLI wrapper. It replaces the previous `core/judge.py`, which judged on
`gpt-4o-mini`, parsed responses with a bare `json.loads` that fell back to `{}`
on malformed output, and passed the judge only a title despite a prompt claiming
to judge on metadata.

Usage:
    python -m jobs.eval_judge                        # yesterday, batch mode
    python -m jobs.eval_judge --date 2026-07-31      # a specific date
    python -m jobs.eval_judge --days 7               # backfill the last 7 days
    python -m jobs.eval_judge --sample-size 100      # more queries
    python -m jobs.eval_judge --sync                 # synchronous (2x cost, instant)
    python -m jobs.eval_judge --dry-run              # show what would be judged
"""

import argparse
import asyncio
import logging
import uuid
from datetime import date, timedelta

from core.config import DATABASE_URL
from core.db import get_engine

from reelix_eval import store
from reelix_eval.judge import (
    DEFAULT_JUDGE_MODEL,
    JUDGE_KEY_ENV,
    JudgeConfig,
    build_client,
    judge_queries,
    judge_queries_batch,
    persist,
    summarize,
)

logger = logging.getLogger(__name__)

DEFAULT_SAMPLE_SIZE = 50


def _validate_env() -> None:
    import os

    missing = []
    if not DATABASE_URL:
        missing.append("DATABASE_URL")
    if not os.getenv(JUDGE_KEY_ENV):
        missing.append(JUDGE_KEY_ENV)
    if missing:
        raise EnvironmentError(f"Missing required env vars: {', '.join(missing)}")


async def _run_for_date(
    engine,
    target_date: date,
    sample_size: int,
    cfg: JudgeConfig,
    use_batch: bool,
    dry_run: bool,
) -> None:
    eval_run_id = f"judge-{target_date.isoformat()}-{uuid.uuid4().hex[:8]}"

    query_ids = store.sample_queries(
        engine,
        target_date,
        target_date + timedelta(days=1),
        limit=sample_size,
        query_filter="random",
    )
    if not query_ids:
        logger.info("No eligible queries for %s — skipping.", target_date)
        return

    details = [
        d for d in (store.get_query_detail(engine, q) for q in query_ids) if d
    ]
    if not details:
        logger.info("No assemblable query detail for %s — skipping.", target_date)
        return

    logger.info(
        "%s: %d queries, %d served candidates (%d sampled ids unresolvable)",
        target_date,
        len(details),
        sum(len(d.served) for d in details),
        len(query_ids) - len(details),
    )

    if dry_run:
        for d in details[:10]:
            logger.info("  would judge %s — %r", d.query_id[:12], d.query_text[:60])
        return

    client = build_client()
    if use_batch:
        judgements = await judge_queries_batch(client, details, cfg)
    else:
        judgements = await judge_queries(client, details, cfg)

    persist(engine, judgements, eval_run_id, cfg)
    _print_summary(summarize(judgements, cfg), eval_run_id, use_batch)


def _print_summary(s: dict, eval_run_id: str, use_batch: bool) -> None:
    def f(key, spec="{:.2f}"):
        v = s.get(key)
        return spec.format(v) if v is not None else "—"

    print(f"\n{'=' * 62}")
    print(f"  Reelix judge — {eval_run_id}")
    print(f"  {s['queries_ok']}/{s['queries']} queries, {s['items']} candidates")
    print(f"{'=' * 62}")
    print("\n  [RECOMMENDATION QUALITY]  (evaluates the curator)")
    print(f"    Relevance                      {f('avg_relevance')} / 5")
    print(f"    Novelty                        {f('avg_novelty')} / 5")
    print(f"    Spec violations (judge)        {f('spec_violation_rate_judge', '{:.1%}')}")
    print("\n  [ORCHESTRATOR + SLATE]")
    print(f"    Spec fidelity                  {f('avg_spec_fidelity')} / 5")
    print(f"    List coherence                 {f('avg_list_coherence')} / 5")
    print("\n  [EXPLANATION QUALITY]  (evaluates the explanation agent)")
    print(f"    Explanation quality            {f('avg_explanation_quality')} / 5")
    print(f"    Grounded (no hallucination)    {f('grounded_rate', '{:.1%}')}")
    print("\n  [JUDGE CALIBRATION]")
    print(f"    Disagreement with code check   {f('spec_check_disagreement_rate', '{:.1%}')}")

    tiers = s.get("avg_relevance_by_tier") or {}
    if tiers:
        print("\n  [CURATOR AGREEMENT]  mean judged relevance per curator tier")
        for tier in ("strong_match", "moderate_match", "no_match"):
            if tier in tiers:
                print(f"    {tier:30} {tiers[tier]:.2f} / 5")

    tin, tout = s["total_input_tokens"], s["total_output_tokens"]
    rate_in, rate_out = (1.5, 7.5) if use_batch else (3.0, 15.0)
    cost = tin / 1e6 * rate_in + tout / 1e6 * rate_out
    print("\n  [COST]")
    print(f"    Tokens                         {tin:,} in / {tout:,} out")
    print(f"    Approx cost                    ${cost:.4f}"
          f"  ({'batch' if use_batch else 'sync'}, {s['judge_model']})")
    print(f"{'=' * 62}\n")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Run LLM-as-judge evaluation on sampled Reelix queries.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--date", default=None, help="Target date (YYYY-MM-DD). Default: yesterday.")
    p.add_argument("--days", type=int, default=None,
                   help="Backfill this many days ending at --date (or yesterday).")
    p.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE,
                   help=f"Queries to sample per day. Default: {DEFAULT_SAMPLE_SIZE}.")
    p.add_argument("--model", default=DEFAULT_JUDGE_MODEL,
                   help=f"Judge model. Default: {DEFAULT_JUDGE_MODEL}.")
    p.add_argument("--effort", default="low", choices=["low", "medium", "high", "xhigh", "max"],
                   help="Judge effort level. Default: low.")
    p.add_argument("--sync", action="store_true",
                   help="Use the synchronous API instead of the Batch API. "
                        "Instant but roughly twice the cost.")
    p.add_argument("--dry-run", action="store_true",
                   help="List what would be judged without calling the API.")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if not args.dry_run:
        _validate_env()

    end_date = date.fromisoformat(args.date) if args.date else date.today() - timedelta(days=1)
    days = [end_date - timedelta(days=i) for i in range(args.days or 1)]

    cfg = JudgeConfig(model=args.model, effort=args.effort)
    use_batch = not args.sync

    logger.info("=" * 60)
    logger.info("Reelix eval_judge — %s", cfg.model)
    logger.info(
        "Dates: %s | sample: %d/day | mode: %s",
        ", ".join(d.isoformat() for d in reversed(days)),
        args.sample_size,
        "batch (50% cheaper)" if use_batch else "sync",
    )
    logger.info("=" * 60)

    engine = get_engine()
    for d in reversed(days):
        asyncio.run(
            _run_for_date(engine, d, args.sample_size, cfg, use_batch, args.dry_run)
        )

    logger.info("Done.")


if __name__ == "__main__":
    main()