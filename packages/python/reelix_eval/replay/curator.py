"""Re-run the curator stage against the working tree.

This is the verification engine: it imports `CURATOR_PROMPT_S`, the user-prompt
builder, and `apply_curator_tiers` from `reelix_agent` — an *editable* install
pointing at the working tree — so a prompt edit is picked up with no reinstall
and no redeploy. Feed it a frozen eval set and it reproduces production's curator
call (same model, same temperature, same two-batch split) against whatever the
prompts currently say.

The system under test stays on OpenAI. Claude is the evaluator, never the thing
being measured.

**Noise floor.** The curator runs at `temperature=0.1`, so a replay is not
deterministic. Measured by replaying one frozen 20-case set twice (2026-08-01,
`gpt-4.1-mini`), run-to-run variation is:

    strong_count ±0.25   moderate_count ±0.15   no_match_count ±0.10
    served_count ±0.20   served_overlap  ~0.80 against a fixed baseline

So an *unchanged* replay scores ~0.80 served overlap, not 1.0, and tier counts
wander by a quarter of a title. Any A/B claiming a win on a set this size has to
move a metric by more than that to mean anything — treat smaller deltas as noise,
and widen the eval set before trusting them.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from reelix_agent.core.types import RecQuerySpec
from reelix_agent.curator.curator_agent import run_curator_agent
from reelix_agent.curator.curator_tiers import apply_curator_tiers
from reelix_ranking.types import Candidate

if TYPE_CHECKING:
    from reelix_core.llm_client import LlmClient

    from reelix_eval.replay.evalset import EvalCase

logger = logging.getLogger(__name__)

#: Matches production: `recommendation_tool` splits candidates into 2 batches and
#: evaluates them with `asyncio.gather`.
CURATOR_BATCHES = 2
DEFAULT_CONCURRENCY = 3


@dataclass
class CaseReplay:
    query_id: str
    query_text: str
    ok: bool = True
    error: str | None = None
    served_ids: list[int] = field(default_factory=list)
    tier_stats: dict = field(default_factory=dict)
    #: media_id → {genre_fit, tone_fit, theme_fit, total_fit, category}
    fits: dict[int, dict] = field(default_factory=dict)
    baseline_served_ids: list[int] = field(default_factory=list)
    baseline_tier_stats: dict = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def served_overlap(self) -> float | None:
        """Jaccard overlap between the replayed slate and the frozen baseline."""
        a, b = set(self.served_ids), set(self.baseline_served_ids)
        if not a and not b:
            return None
        return len(a & b) / len(a | b)


@dataclass
class ReplayRun:
    label: str
    cases: list[CaseReplay] = field(default_factory=list)

    @property
    def ok_cases(self) -> list[CaseReplay]:
        return [c for c in self.cases if c.ok]

    def summary(self) -> dict:
        ok = self.ok_cases
        overlaps = [c.served_overlap for c in ok if c.served_overlap is not None]

        def _tier_mean(key: str, source: str) -> float | None:
            stats = [
                getattr(c, source).get(key)
                for c in ok
                if getattr(c, source) and getattr(c, source).get(key) is not None
            ]
            return sum(stats) / len(stats) if stats else None

        # Per-dimension means over every scored candidate. Without these a rubric
        # edit can only be observed through its downstream slate effect, which is
        # the weakest possible signal: the mechanism the edit targets stays
        # unmeasured, so "no slate change" cannot be distinguished from "the
        # scores moved but the tiering absorbed it".
        dims = ("genre_fit", "tone_fit", "theme_fit", "total_fit")
        dim_means: dict[str, float | None] = {}
        for d in dims:
            vals = [
                f[d]
                for c in ok
                for f in c.fits.values()
                if f.get(d) is not None
            ]
            dim_means[f"mean_{d}"] = sum(vals) / len(vals) if vals else None
        dim_means["scored_candidates"] = sum(len(c.fits) for c in ok)

        return {
            "label": self.label,
            "cases": len(self.cases),
            "cases_ok": len(ok),
            "cases_failed": len(self.cases) - len(ok),
            **dim_means,
            "mean_served_overlap": (
                sum(overlaps) / len(overlaps) if overlaps else None
            ),
            "mean_strong_count": _tier_mean("strong_count", "tier_stats"),
            "mean_moderate_count": _tier_mean("moderate_count", "tier_stats"),
            "mean_no_match_count": _tier_mean("no_match_count", "tier_stats"),
            "mean_served_count": _tier_mean("served_count", "tier_stats"),
            "baseline_mean_strong_count": _tier_mean("strong_count", "baseline_tier_stats"),
            "baseline_mean_moderate_count": _tier_mean(
                "moderate_count", "baseline_tier_stats"
            ),
            "baseline_mean_no_match_count": _tier_mean(
                "no_match_count", "baseline_tier_stats"
            ),
            "baseline_mean_served_count": _tier_mean(
                "served_count", "baseline_tier_stats"
            ),
            "total_input_tokens": sum(c.input_tokens for c in ok),
            "total_output_tokens": sum(c.output_tokens for c in ok),
        }


def _to_candidates(case: "EvalCase") -> list[Candidate]:
    """Rebuild the `Candidate` objects the curator prompt builder expects."""
    return [
        Candidate(
            id=int(c.media_id),
            payload={
                "title": c.title,
                "genres": c.genres,
                "keywords": c.keywords,
                "overview": c.overview,
                "release_year": c.release_year,
                "watch_providers": c.watch_providers,
                "llm_context": c.llm_context,
            },
        )
        for c in case.candidates
    ]


def _to_spec(case: "EvalCase") -> RecQuerySpec:
    """Rebuild the spec. Falls back to a bare spec when none was logged."""
    raw = dict(case.spec_json or {})
    raw.setdefault("query_text", case.query_text)
    try:
        return RecQuerySpec(**raw)
    except Exception as e:
        logger.warning(
            "Spec rebuild failed for %s (%s) — falling back to query_text only",
            case.query_id,
            e,
        )
        return RecQuerySpec(query_text=case.query_text)


async def replay_case(
    case: "EvalCase",
    llm_client: "LlmClient",
    semaphore: asyncio.Semaphore | None = None,
) -> CaseReplay:
    """Re-run curator + tiering for one frozen case."""
    result = CaseReplay(
        query_id=case.query_id,
        query_text=case.query_text,
        baseline_served_ids=list(case.baseline_served_ids),
        baseline_tier_stats=dict(case.baseline_tier_stats or {}),
    )

    candidates = _to_candidates(case)
    spec = _to_spec(case)
    sem = semaphore or asyncio.Semaphore(DEFAULT_CONCURRENCY)

    # Same split as recommendation_tool: two batches, evaluated in parallel.
    mid = len(candidates) // CURATOR_BATCHES
    batches = [candidates[:mid], candidates[mid:]]

    async def _eval(batch: list[Candidate]):
        async with sem:
            return await run_curator_agent(
                query_text=spec.query_text,
                spec=spec,
                candidates=batch,
                llm_client=llm_client,
                user_signals=None,
            )

    try:
        outputs = await asyncio.gather(*(_eval(b) for b in batches))
    except Exception as e:
        result.ok = False
        result.error = f"{type(e).__name__}: {e}"
        return result

    evaluations: list[dict] = []
    for content, usage in outputs:
        result.input_tokens += usage.input_tokens or 0
        result.output_tokens += usage.output_tokens or 0
        try:
            evaluations.extend(json.loads(content).get("evaluation_results", []))
        except (json.JSONDecodeError, AttributeError) as e:
            result.ok = False
            result.error = f"curator output parse error: {e}"
            return result

    final, tier_stats = apply_curator_tiers(
        evaluation_results=evaluations,
        candidates=candidates,
        limit=spec.num_recs or 8,
    )

    result.served_ids = [int(c.id) for c in final]
    result.tier_stats = tier_stats
    # apply_curator_tiers stamps its verdict onto each candidate's payload.
    result.fits = {
        int(c.id): {
            "genre_fit": (c.payload or {}).get("curator_genre_fit"),
            "tone_fit": (c.payload or {}).get("curator_tone_fit"),
            "theme_fit": (c.payload or {}).get("curator_theme_fit"),
            "total_fit": (c.payload or {}).get("curator_total_fit"),
            "category": (c.payload or {}).get("curator_category"),
        }
        for c in candidates
    }
    return result


async def replay(
    cases: list["EvalCase"],
    llm_client: "LlmClient",
    label: str = "working-tree",
    concurrency: int = DEFAULT_CONCURRENCY,
) -> ReplayRun:
    """Replay every case against the curator prompts in the working tree."""
    sem = asyncio.Semaphore(concurrency)
    results = await asyncio.gather(
        *(replay_case(c, llm_client, sem) for c in cases)
    )
    run = ReplayRun(label=label, cases=list(results))
    logger.info("Replay %s: %s", label, run.summary())
    return run