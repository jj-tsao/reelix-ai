"""LLM-as-judge execution and persistence.

Runs two independent Claude calls per query (recommendation quality, then
explanation quality), validates both against a schema, and upserts the results.

Two structural fixes over the original `core/judge.py`:

* Output is parsed via `client.messages.parse(output_format=...)`, so a malformed
  response raises instead of silently degrading to `{}` and reading, in
  aggregate, exactly like a quality regression.
* Token counts live on the per-query record only. The old code stamped the same
  totals onto every candidate row, so any `SUM()` over-counted by the number of
  candidates.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from sqlalchemy import text
from sqlalchemy.engine import Engine

from reelix_eval.judge.prompts import (
    EXPL_JUDGE_SYSTEM,
    REC_JUDGE_SYSTEM,
    build_expl_prompt,
    build_rec_prompt,
)
from reelix_eval.judge.schema import ExplanationQualityVerdict, RecQualityVerdict
from reelix_eval.judge.spec_check import check_spec_violation

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic

    from reelix_eval.store import QueryDetail

logger = logging.getLogger(__name__)

#: Sonnet 5 over Opus 5, chosen by measurement rather than instinct. On a 6-query
#: / 43-item A/B (2026-08-01) against Opus 5 as reference:
#:
#:     model            $/query   rel r   rel MAE   within±1   nov r   spec agree
#:     opus-5           $0.0654   1.00      0.00       100%    1.00        100%
#:     sonnet-5         $0.0380   0.81      0.40        95%    0.89        100%
#:     haiku-4-5        $0.0107   0.61      0.70        84%    0.52         98%
#:
#: Sonnet 5 tracks Opus closely (95% of items within one point, identical
#: spec_violation calls) at 58% of the cost. Haiku 4.5 was rejected: novelty
#: correlation collapses to 0.52 — and novelty is exactly the axis that would
#: reveal the curator getting predictable — plus it grades systematically easier,
#: which biases a judge toward under-reporting regressions.
#:
#: Re-run scratch A/B before changing this; the judge is the measuring instrument
#: for every other number in the harness.
DEFAULT_JUDGE_MODEL = "claude-sonnet-5"
DEFAULT_EFFORT = "low"
DEFAULT_MAX_TOKENS = 8000
DEFAULT_CONCURRENCY = 4

#: Prompt caching is deliberately NOT used. Both system prompts sit below the
#: cacheable minimum (rec=920, expl=400 tokens; Sonnet 5 requires 1024, Opus 5
#: 512), so `cache_control` is a silent no-op — verified: on Sonnet 5 a repeated
#: call reports cache_creation=0 / cache_read=0. The rest of each request is the
#: per-query candidate list, which by definition can't be shared. Padding a judge
#: rubric with filler to clear the threshold would save ~$0.37/month and make the
#: prompt worse; not worth it.

JudgeStatus = Literal["ok", "refused", "error"]

#: Deliberately NOT `ANTHROPIC_API_KEY`. That name is what the Anthropic SDK and
#: the Claude Code CLI both resolve first, so exporting it would silently move
#: Agent SDK runs off the plan credit and onto pay-as-you-go. The judge calls the
#: raw Messages API and is billed separately either way, so it gets its own name
#: and is passed explicitly rather than left in the ambient environment.
JUDGE_KEY_ENV = "REELIX_JUDGE_ANTHROPIC_KEY"


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

#: Models that reject `output_config.effort`. Effort is GA on the Opus 4.5+ and
#: Sonnet 5 lines; older/smaller models 400 on it.
_NO_EFFORT_MODELS = ("claude-haiku-4-5", "claude-sonnet-4-5")


@dataclass
class JudgeConfig:
    model: str = DEFAULT_JUDGE_MODEL
    #: None omits `output_config` entirely — required for models that reject it.
    effort: str | None = DEFAULT_EFFORT
    max_tokens: int = DEFAULT_MAX_TOKENS
    concurrency: int = DEFAULT_CONCURRENCY
    persist: bool = True

    def request_kwargs(self) -> dict:
        """Model-specific request options shared by both judge calls."""
        if self.effort and not self.model.startswith(_NO_EFFORT_MODELS):
            return {"output_config": {"effort": self.effort}}
        return {}

    @property
    def effective_effort(self) -> str | None:
        """The effort actually sent — None when the model doesn't support it."""
        return self.effort if self.request_kwargs() else None


@dataclass
class ItemJudgement:
    query_id: str
    media_id: int
    title: str
    query_text: str
    relevance: int | None = None
    novelty: int | None = None
    rec_reasoning: str | None = None
    spec_violation: bool | None = None
    #: Same question answered deterministically from spec + payload. Disagreement
    #: with `spec_violation` is a calibration signal on the judge itself.
    spec_violation_code: bool | None = None
    explanation_quality: int | None = None
    explanation_grounded: bool | None = None
    expl_reasoning: str | None = None
    curator_total_fit: int | None = None
    curator_tier: str | None = None


@dataclass
class QueryJudgement:
    query_id: str
    query_text: str
    status: JudgeStatus = "ok"
    error: str | None = None
    spec_fidelity: int | None = None
    list_coherence: int | None = None
    query_reasoning: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    items: list[ItemJudgement] = field(default_factory=list)

    @property
    def spec_disagreements(self) -> int:
        return sum(
            1
            for i in self.items
            if i.spec_violation is not None
            and i.spec_violation_code is not None
            and i.spec_violation != i.spec_violation_code
        )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

def build_client(api_key: str | None = None, timeout: float = 120.0):
    """Build the judge's Anthropic client with an explicitly-passed key.

    Never falls back to the SDK's ambient credential resolution — see
    `JUDGE_KEY_ENV`. Imported lazily so `reelix_eval.judge` stays importable
    without `anthropic` installed.
    """
    import os

    from anthropic import AsyncAnthropic

    key = api_key or os.getenv(JUDGE_KEY_ENV)
    if not key:
        raise RuntimeError(
            f"{JUDGE_KEY_ENV} not set. Add it to apps/jobs/.env — do not "
            "export ANTHROPIC_API_KEY, which would shadow the Claude Code login."
        )
    return AsyncAnthropic(api_key=key, timeout=timeout, max_retries=3)


# ---------------------------------------------------------------------------
# LLM calls
# ---------------------------------------------------------------------------

async def _call_rec_judge(
    client: "AsyncAnthropic", detail: "QueryDetail", cfg: JudgeConfig
) -> tuple[RecQualityVerdict | None, int, int, JudgeStatus]:
    resp = await client.messages.parse(
        model=cfg.model,
        max_tokens=cfg.max_tokens,
        system=REC_JUDGE_SYSTEM,
        messages=[{"role": "user", "content": build_rec_prompt(detail)}],
        output_format=RecQualityVerdict,
        **cfg.request_kwargs(),
    )
    usage = resp.usage
    in_tok = getattr(usage, "input_tokens", 0) or 0
    out_tok = getattr(usage, "output_tokens", 0) or 0

    # Safety classifiers can decline with HTTP 200 and empty content — reading
    # content unconditionally would blow up here.
    if resp.stop_reason == "refusal":
        logger.warning("Rec judge refused for %s", detail.query_id)
        return None, in_tok, out_tok, "refused"

    return resp.parsed_output, in_tok, out_tok, "ok"


async def _call_expl_judge(
    client: "AsyncAnthropic", detail: "QueryDetail", cfg: JudgeConfig
) -> tuple[ExplanationQualityVerdict | None, int, int, JudgeStatus]:
    prompt = build_expl_prompt(detail)
    if not prompt:
        # No "why" text was ever logged for this query. Skipping is correct —
        # scoring absent explanations would blame the explanation agent for a
        # gap in telemetry.
        return None, 0, 0, "ok"

    resp = await client.messages.parse(
        model=cfg.model,
        max_tokens=cfg.max_tokens,
        system=EXPL_JUDGE_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_format=ExplanationQualityVerdict,
        **cfg.request_kwargs(),
    )
    usage = resp.usage
    in_tok = getattr(usage, "input_tokens", 0) or 0
    out_tok = getattr(usage, "output_tokens", 0) or 0

    if resp.stop_reason == "refusal":
        logger.warning("Explanation judge refused for %s", detail.query_id)
        return None, in_tok, out_tok, "refused"

    return resp.parsed_output, in_tok, out_tok, "ok"


async def judge_query(
    client: "AsyncAnthropic",
    detail: "QueryDetail",
    cfg: JudgeConfig,
    semaphore: asyncio.Semaphore | None = None,
) -> QueryJudgement:
    """Run both judge calls for one query and merge them into one record."""
    sem = semaphore or asyncio.Semaphore(cfg.concurrency)

    async def _guarded(coro_fn):
        async with sem:
            return await coro_fn(client, detail, cfg)

    result = QueryJudgement(query_id=detail.query_id, query_text=detail.query_text)

    try:
        (rec, rec_in, rec_out, rec_status), (expl, expl_in, expl_out, expl_status) = (
            await asyncio.gather(
                _guarded(_call_rec_judge),
                _guarded(_call_expl_judge),
            )
        )
    except Exception as e:
        logger.error("Judge failed for %s: %s", detail.query_id, e)
        result.status = "error"
        result.error = f"{type(e).__name__}: {e}"
        return result

    return merge_verdicts(
        detail,
        rec=rec,
        expl=expl,
        input_tokens=rec_in + expl_in,
        output_tokens=rec_out + expl_out,
        status="refused" if "refused" in (rec_status, expl_status) else "ok",
    )


def merge_verdicts(
    detail: "QueryDetail",
    *,
    rec: RecQualityVerdict | None,
    expl: ExplanationQualityVerdict | None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    status: JudgeStatus = "ok",
) -> QueryJudgement:
    """Fold both verdicts into one record, adding the deterministic spec check.

    Shared by the synchronous and Batch API paths so they can't drift apart.
    Iterates `detail.served` rather than the verdict items, so a candidate the
    judge silently skipped still produces a row (with null scores) instead of
    vanishing from the sample.
    """
    result = QueryJudgement(
        query_id=detail.query_id,
        query_text=detail.query_text,
        status=status,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )

    if rec:
        result.spec_fidelity = rec.spec_fidelity
        result.list_coherence = rec.list_coherence
        result.query_reasoning = rec.query_reasoning

    rec_by_id = {i.media_id: i for i in (rec.items if rec else [])}
    expl_by_id = {i.media_id: i for i in (expl.items if expl else [])}

    for c in detail.served:
        r = rec_by_id.get(c.media_id)
        e = expl_by_id.get(c.media_id)
        code_check = check_spec_violation(detail.spec_json, c)

        result.items.append(
            ItemJudgement(
                query_id=detail.query_id,
                media_id=c.media_id,
                title=c.title,
                query_text=detail.query_text,
                relevance=r.relevance if r else None,
                novelty=r.novelty if r else None,
                rec_reasoning=r.reasoning if r else None,
                spec_violation=r.spec_violation if r else None,
                spec_violation_code=code_check.violated,
                explanation_quality=e.explanation_quality if e else None,
                explanation_grounded=e.explanation_grounded if e else None,
                expl_reasoning=e.reasoning if e else None,
                curator_total_fit=c.total_fit,
                curator_tier=c.tier,
            )
        )

    return result


async def judge_queries(
    client: "AsyncAnthropic",
    details: list["QueryDetail"],
    cfg: JudgeConfig | None = None,
) -> list[QueryJudgement]:
    """Judge many queries, bounded by `cfg.concurrency`."""
    cfg = cfg or JudgeConfig()
    sem = asyncio.Semaphore(cfg.concurrency)
    results = await asyncio.gather(
        *(judge_query(client, d, cfg, sem) for d in details)
    )
    return list(results)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

_ITEM_UPSERT = text("""
    INSERT INTO judge_evaluations (
        eval_run_id, query_id, media_id, query_text, title,
        relevance, novelty, rec_reasoning,
        explanation_quality, expl_reasoning,
        spec_violation, spec_violation_code, explanation_grounded,
        curator_total_fit, curator_tier,
        judge_model, judge_effort, input_tokens, output_tokens
    ) VALUES (
        :eval_run_id, :query_id, :media_id, :query_text, :title,
        :relevance, :novelty, :rec_reasoning,
        :explanation_quality, :expl_reasoning,
        :spec_violation, :spec_violation_code, :explanation_grounded,
        :curator_total_fit, :curator_tier,
        :judge_model, :judge_effort, NULL, NULL
    )
    ON CONFLICT (eval_run_id, query_id, media_id) DO UPDATE SET
        relevance = EXCLUDED.relevance,
        novelty = EXCLUDED.novelty,
        rec_reasoning = EXCLUDED.rec_reasoning,
        explanation_quality = EXCLUDED.explanation_quality,
        expl_reasoning = EXCLUDED.expl_reasoning,
        spec_violation = EXCLUDED.spec_violation,
        spec_violation_code = EXCLUDED.spec_violation_code,
        explanation_grounded = EXCLUDED.explanation_grounded,
        judge_effort = EXCLUDED.judge_effort,
        created_at = now()
""")

_QUERY_UPSERT = text("""
    INSERT INTO judge_query_evaluations (
        eval_run_id, query_id, query_text,
        spec_fidelity, list_coherence, reasoning,
        judge_model, judge_effort, input_tokens, output_tokens, status
    ) VALUES (
        :eval_run_id, :query_id, :query_text,
        :spec_fidelity, :list_coherence, :reasoning,
        :judge_model, :judge_effort, :input_tokens, :output_tokens, :status
    )
    ON CONFLICT (eval_run_id, query_id) DO UPDATE SET
        spec_fidelity = EXCLUDED.spec_fidelity,
        list_coherence = EXCLUDED.list_coherence,
        reasoning = EXCLUDED.reasoning,
        input_tokens = EXCLUDED.input_tokens,
        output_tokens = EXCLUDED.output_tokens,
        status = EXCLUDED.status,
        created_at = now()
""")


def persist(
    engine: Engine,
    judgements: list[QueryJudgement],
    eval_run_id: str,
    cfg: JudgeConfig | None = None,
) -> None:
    """Upsert judgements. Tokens are written to the per-query table only."""
    cfg = cfg or JudgeConfig()
    if not judgements:
        return

    with engine.begin() as conn:
        for j in judgements:
            conn.execute(
                _QUERY_UPSERT,
                {
                    "eval_run_id": eval_run_id,
                    "query_id": j.query_id,
                    "query_text": j.query_text,
                    "spec_fidelity": j.spec_fidelity,
                    "list_coherence": j.list_coherence,
                    "reasoning": j.query_reasoning,
                    "judge_model": cfg.model,
                    "judge_effort": cfg.effective_effort,
                    "input_tokens": j.input_tokens,
                    "output_tokens": j.output_tokens,
                    "status": j.status,
                },
            )
            for i in j.items:
                conn.execute(
                    _ITEM_UPSERT,
                    {
                        "eval_run_id": eval_run_id,
                        "query_id": i.query_id,
                        "media_id": i.media_id,
                        "query_text": i.query_text,
                        "title": i.title,
                        "relevance": i.relevance,
                        "novelty": i.novelty,
                        "rec_reasoning": i.rec_reasoning,
                        "explanation_quality": i.explanation_quality,
                        "expl_reasoning": i.expl_reasoning,
                        "spec_violation": i.spec_violation,
                        "spec_violation_code": i.spec_violation_code,
                        "explanation_grounded": i.explanation_grounded,
                        "curator_total_fit": i.curator_total_fit,
                        "curator_tier": i.curator_tier,
                        "judge_model": cfg.model,
                        "judge_effort": cfg.effective_effort,
                    },
                )

    n_items = sum(len(j.items) for j in judgements)
    logger.info(
        "Upserted %d query judgements (%d items) for run %s",
        len(judgements),
        n_items,
        eval_run_id,
    )


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def summarize(judgements: list[QueryJudgement], cfg: JudgeConfig | None = None) -> dict:
    """Aggregate judgements into the numbers worth printing or reporting."""
    cfg = cfg or JudgeConfig()
    items = [i for j in judgements for i in j.items]

    def _mean(vals: list) -> float | None:
        clean = [v for v in vals if v is not None]
        return sum(clean) / len(clean) if clean else None

    paired = [
        i
        for i in items
        if i.spec_violation is not None and i.spec_violation_code is not None
    ]
    disagreements = sum(1 for i in paired if i.spec_violation != i.spec_violation_code)

    by_tier: dict[str, list[int]] = {}
    for i in items:
        if i.relevance is not None and i.curator_tier:
            by_tier.setdefault(i.curator_tier, []).append(i.relevance)

    return {
        "judge_model": cfg.model,
        "judge_effort": cfg.effective_effort,
        "queries": len(judgements),
        "queries_ok": sum(1 for j in judgements if j.status == "ok"),
        "queries_failed": sum(1 for j in judgements if j.status != "ok"),
        "items": len(items),
        "avg_relevance": _mean([i.relevance for i in items]),
        "avg_novelty": _mean([i.novelty for i in items]),
        "avg_explanation_quality": _mean([i.explanation_quality for i in items]),
        "avg_spec_fidelity": _mean([j.spec_fidelity for j in judgements]),
        "avg_list_coherence": _mean([j.list_coherence for j in judgements]),
        "grounded_rate": _mean(
            [
                1.0 if i.explanation_grounded else 0.0
                for i in items
                if i.explanation_grounded is not None
            ]
        ),
        "spec_violation_rate_judge": _mean(
            [1.0 if i.spec_violation else 0.0 for i in items if i.spec_violation is not None]
        ),
        "spec_violation_rate_code": _mean(
            [
                1.0 if i.spec_violation_code else 0.0
                for i in items
                if i.spec_violation_code is not None
            ]
        ),
        "spec_check_disagreement_rate": (
            disagreements / len(paired) if paired else None
        ),
        "avg_relevance_by_tier": {t: sum(v) / len(v) for t, v in by_tier.items()},
        "total_input_tokens": sum(j.input_tokens for j in judgements),
        "total_output_tokens": sum(j.output_tokens for j in judgements),
    }