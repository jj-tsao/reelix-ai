"""
Investigator job — investigates Reelix quality from the production logs.

A thin argparse wrapper over `reelix_eval.agent.run`, matching the jobs/*
convention: the logic lives in the package, the job is the entry point.

Named `investigate` rather than `eval_agent` because the agent's remit is wider
than eval: it triages metrics, reads real queries, locates the responsible code
and proposes diffs. The sibling `eval_judge` and `eval_metrics` jobs keep their
names — those really are just eval.

Read-only by default. `--apply` additionally lets the agent branch and edit
prompt/config files; pushing is denied unconditionally in every mode.

Usage:
    python -m jobs.investigate --since 7d                    # investigate + report
    python -m jobs.investigate --since 7d --apply            # + branch, edit, verify
    python -m jobs.investigate --query-ids a,b,c             # deep-dive specific queries
    python -m jobs.investigate --focus curator --since 14d   # scope to one stage
    python -m jobs.investigate --replay-only --evalset base  # re-verify a branch
    python -m jobs.investigate --since 7d --dry-run          # print the plan, no LLM calls
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from core.config import DATABASE_URL, OPENAI_API_KEY

from reelix_eval.agent import RunConfig, run
from reelix_eval.judge import DEFAULT_JUDGE_MODEL

logger = logging.getLogger(__name__)

#: This app's own directory. Output is anchored here rather than to the caller's
#: cwd so `python -m jobs.investigate` writes to the same place from anywhere.
APP_ROOT = Path(__file__).resolve().parents[1]


def _validate_env(cfg: RunConfig) -> None:
    missing = []
    if not DATABASE_URL:
        missing.append("DATABASE_URL")
    if not OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY (needed for curator replay)")
    if missing:
        raise EnvironmentError(f"Missing required env vars: {', '.join(missing)}")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Investigate Reelix recommendation quality from production logs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--since", default="7d",
                   help="Window to investigate: 7d, 2w, or an ISO date. Default: 7d.")
    p.add_argument("--baseline", default=None,
                   help="Baseline window to compare against. Default: same length, "
                        "immediately preceding --since.")
    p.add_argument("--focus", default=None,
                   choices=["orchestrator", "retrieval", "curator", "explanation"],
                   help="Scope the investigation to one stage.")
    p.add_argument("--query-ids", default=None,
                   help="Comma-separated query IDs to deep-dive instead of sampling.")
    p.add_argument("--sample-size", type=int, default=20,
                   help="Roughly how many queries to sample for evidence. Default: 20.")
    p.add_argument("--evalset", default="default",
                   help="Eval-set name for snapshot/replay. Default: default.")
    p.add_argument("--evalsets-dir", default=None, type=Path,
                   help=f"Where eval-set snapshots live. Default: {APP_ROOT / 'evalsets'}.")
    p.add_argument("--reports-dir", default=None, type=Path,
                   help=f"Where reports are written. Default: {APP_ROOT / 'reports'}.")
    p.add_argument("--replay-only", action="store_true",
                   help="Skip investigation; replay an existing eval set and score it.")
    p.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL,
                   help=f"Judge model. Default: {DEFAULT_JUDGE_MODEL}.")
    p.add_argument("--model", default="claude-opus-5",
                   help="Model driving the agent itself. Default: claude-opus-5.")
    p.add_argument("--max-turns", type=int, default=60,
                   help="Turn ceiling — the SDK has no wall-clock timeout. Default: 60.")
    p.add_argument("--apply", action="store_true",
                   help="Allow the agent to branch and edit files. Pushing stays denied.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the plan and capability set; make no LLM calls.")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    for noisy in ("httpx", "anthropic", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    cfg = RunConfig(
        since=args.since,
        baseline=args.baseline,
        focus=args.focus,
        evalset=args.evalset,
        evalsets_dir=args.evalsets_dir or APP_ROOT / "evalsets",
        reports_dir=args.reports_dir or APP_ROOT / "reports",
        sample_size=args.sample_size,
        judge_model=args.judge_model,
        model=args.model,
        max_turns=args.max_turns,
        apply_mode=args.apply,
        dry_run=args.dry_run,
    )

    if not args.dry_run:
        _validate_env(cfg)

    logger.info("=" * 60)
    logger.info("Reelix Investigator — run %s", cfg.run_id)
    logger.info(
        "Window: %s | baseline: %s | focus: %s | mode: %s",
        cfg.since, cfg.baseline or "auto", cfg.focus or "all",
        "APPLY (may edit)" if cfg.apply_mode else "read-only",
    )
    logger.info("Agent: %s | judge: %s", cfg.model, cfg.judge_model)
    logger.info("=" * 60)

    try:
        summary = asyncio.run(run(cfg))
    except RuntimeError as e:
        logger.error("%s", e)
        sys.exit(2)

    if args.dry_run:
        print(json.dumps(summary, indent=2))
        return

    logger.info("-" * 60)
    logger.info("turns=%s cost_usd=%s error=%s",
                summary.get("turns"), summary.get("cost_usd"), summary.get("is_error"))
    if summary.get("report"):
        logger.info("Report: %s", summary["report"])
    else:
        logger.warning("No report was written — the agent did not call write_report.")

    if summary.get("is_error"):
        sys.exit(1)


if __name__ == "__main__":
    main()
