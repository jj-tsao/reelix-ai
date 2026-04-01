"""
LLM-as-judge evaluation job for Reelix recommendations.

Samples queries from a target date, evaluates recommendation quality
(relevance + novelty) and explanation quality with separate LLM calls,
and persists scores to the judge_evaluations table.

Usage:
    python -m jobs.eval_judge                             # yesterday, 50 samples
    python -m jobs.eval_judge --date 2026-03-30            # specific date
    python -m jobs.eval_judge --sample-size 100            # more samples
    python -m jobs.eval_judge --model gpt-4o-mini          # specify judge model
"""

import argparse
import asyncio
import logging
import uuid
from datetime import date, timedelta

from core.config import DATABASE_URL, OPENAI_API_KEY
from core.db import get_engine
from core.judge import (
    assemble_query_context,
    judge_query,
    print_judge_summary,
    sample_queries,
    upsert_judge_scores,
)

from reelix_core.llm_client import LlmClient

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_SAMPLE_SIZE = 50
MAX_CONCURRENT = 5


def _validate_env():
    missing = []
    if not DATABASE_URL:
        missing.append("DATABASE_URL")
    if not OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")
    if missing:
        raise EnvironmentError(f"Missing required env vars: {', '.join(missing)}")


async def _run_judge(
    engine,
    target_date: date,
    sample_size: int,
    judge_model: str,
) -> None:
    eval_run_id = f"judge-{target_date.isoformat()}-{uuid.uuid4().hex[:8]}"
    logger.info("Eval run: %s", eval_run_id)

    # 1) Sample queries
    query_ids = sample_queries(engine, target_date, sample_size)
    if not query_ids:
        logger.info("No eligible queries found for %s — skipping.", target_date)
        return

    # 2) Assemble context for each query
    contexts = []
    for qid in query_ids:
        ctx = assemble_query_context(engine, qid)
        if ctx and ctx.candidates:
            contexts.append(ctx)

    if not contexts:
        logger.info("No candidate data found for sampled queries — skipping.")
        return

    logger.info("Assembled context for %d queries (%d skipped)",
                len(contexts), len(query_ids) - len(contexts))

    # 3) Run judge LLM calls
    llm = LlmClient(model=judge_model, api_key=OPENAI_API_KEY, timeout=30.0)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    tasks = [judge_query(llm, ctx, judge_model, semaphore) for ctx in contexts]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_scores = []
    errors = 0
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error("Judge failed for %s: %s", contexts[i].query_id, result)
            errors += 1
        else:
            all_scores.extend(result)

    if errors:
        logger.warning("%d/%d queries failed", errors, len(contexts))

    # 4) Persist
    if all_scores:
        upsert_judge_scores(engine, all_scores, eval_run_id, judge_model)

    # 5) Summary
    print_judge_summary(all_scores, judge_model)


def main():
    parser = argparse.ArgumentParser(
        description="Run LLM-as-judge evaluation on sampled Reelix queries."
    )
    parser.add_argument(
        "--date", type=str, default=None,
        help="Target date (YYYY-MM-DD). Defaults to yesterday.",
    )
    parser.add_argument(
        "--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE,
        help=f"Number of queries to sample. Default: {DEFAULT_SAMPLE_SIZE}.",
    )
    parser.add_argument(
        "--model", type=str, default=DEFAULT_MODEL,
        help=f"Judge model. Default: {DEFAULT_MODEL}.",
    )
    args = parser.parse_args()
    _validate_env()

    if args.date:
        target_date = date.fromisoformat(args.date)
    else:
        target_date = date.today() - timedelta(days=1)

    logger.info("=" * 60)
    logger.info("Reelix eval_judge job")
    logger.info("Date: %s | Sample size: %d | Model: %s",
                target_date, args.sample_size, args.model)
    logger.info("=" * 60)

    engine = get_engine()
    asyncio.run(_run_judge(engine, target_date, args.sample_size, args.model))

    logger.info("Done.")


if __name__ == "__main__":
    main()
