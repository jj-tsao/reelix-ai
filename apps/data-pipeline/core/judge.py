"""
LLM-as-judge evaluation for Reelix recommendations.

Evaluates sampled queries with two independent LLM calls:
1. Recommendation quality (relevance + novelty) — evaluates curator picks
   WITHOUT seeing "why" explanations, to avoid bias
2. Explanation quality — evaluates explanation agent output separately

Usage: called from jobs/eval_judge.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Engine

from reelix_core.llm_client import LlmClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

REC_JUDGE_SYSTEM_PROMPT = """\
You are an expert evaluator of movie/TV recommendations.

Given a user's search query and a list of recommended titles,
score each recommendation independently. You are NOT shown the system's
explanations — judge purely based on the title and its metadata.

For each title, assign integer scores (1-5):

1. relevance (1-5):
   - 1 = Completely unrelated to what the user asked for
   - 2 = Tangentially related but clearly not what was intended
   - 3 = Partially relevant — some elements match but it's a stretch
   - 4 = Good fit — clearly matches the request with minor gaps
   - 5 = Excellent fit — exactly what the user was looking for

2. novelty (1-5):
   - 1 = Extremely obvious/predictable choice everyone would suggest
   - 2 = Common, well-known pick for this type of request
   - 3 = Reasonable pick — known but not the first thing that comes to mind
   - 4 = Interesting choice — somewhat unexpected but fitting
   - 5 = Genuinely surprising and creative pick that still fits

For each title also provide a brief reasoning (1 sentence).

Output ONLY valid JSON:
{"evaluations": [{"media_id": 123, "relevance": 4, "novelty": 3, "reasoning": "..."}, ...]}"""

EXPL_JUDGE_SYSTEM_PROMPT = """\
You are evaluating the quality of personalized movie/TV recommendation explanations.

Given a user's search query and recommendations with their "why you'll enjoy it"
explanations, score each explanation's quality.

explanation_quality (1-5):
   - 1 = Generic, could apply to any movie
   - 2 = Mentions the movie but doesn't connect to the user's request
   - 3 = Connects to the request but in a surface-level way
   - 4 = Specific and persuasive — clearly explains why this fits
   - 5 = Insightful — highlights non-obvious connections to the request

For each title also provide a brief reasoning (1 sentence).

Output ONLY valid JSON:
{"evaluations": [{"media_id": 123, "explanation_quality": 4, "reasoning": "..."}, ...]}"""


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class QueryContext:
    query_id: str
    query_text: str
    spec_json: dict | None
    candidates: list[CandidateContext]


@dataclass
class CandidateContext:
    media_id: int
    title: str
    genres: list[str]
    keywords: list[str]
    overview: str
    why_summary: str | None
    curator_total_fit: int | None
    curator_tier: str | None


@dataclass
class JudgeScore:
    query_id: str
    media_id: int
    query_text: str
    title: str
    relevance: int | None = None
    novelty: int | None = None
    rec_reasoning: str | None = None
    explanation_quality: int | None = None
    expl_reasoning: str | None = None
    curator_total_fit: int | None = None
    curator_tier: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------

def sample_queries(engine: Engine, target_date: date, sample_size: int = 50) -> list[str]:
    """Sample query_ids from completed agent requests with curator data."""
    start = datetime(target_date.year, target_date.month, target_date.day)
    end = start + timedelta(days=1)

    with engine.connect() as conn:
        rows = conn.execute(
            text("""
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
                ) sub
                ORDER BY RANDOM()
                LIMIT :limit
            """),
            {"start": start, "end": end, "limit": sample_size},
        ).fetchall()

    query_ids = [r.query_id for r in rows]
    logger.info("Sampled %d query_ids for %s", len(query_ids), target_date)
    return query_ids


def assemble_query_context(engine: Engine, query_id: str) -> QueryContext | None:
    """Pull all data needed to judge a single query."""
    with engine.connect() as conn:
        # Get query text
        q_row = conn.execute(
            text("SELECT query_text FROM rec_queries WHERE query_id = :qid LIMIT 1"),
            {"qid": query_id},
        ).fetchone()

        if not q_row or not q_row.query_text:
            return None

        # Get spec from agent_decisions
        spec_row = conn.execute(
            text("SELECT spec_json FROM agent_decisions WHERE query_id = :qid AND mode = 'RECS' LIMIT 1"),
            {"qid": query_id},
        ).fetchone()

        spec_json = spec_row.spec_json if spec_row else None

        # Get served candidates with curator scores and why_summary
        cand_rows = conn.execute(
            text("""
                SELECT
                    ce.media_id, ce.title,
                    ce.total_fit AS curator_total_fit,
                    ce.tier AS curator_tier,
                    rr.why_summary,
                    rr.meta_breakdown
                FROM curator_evaluations ce
                LEFT JOIN rec_results rr
                    ON ce.query_id = rr.query_id AND ce.media_id = rr.media_id
                WHERE ce.query_id = :qid AND ce.is_served = true
                ORDER BY ce.final_rank
            """),
            {"qid": query_id},
        ).fetchall()

        if not cand_rows:
            return None

        candidates = []
        for r in cand_rows:
            candidates.append(CandidateContext(
                media_id=r.media_id,
                title=r.title or f"ID:{r.media_id}",
                genres=[],
                keywords=[],
                overview="",
                why_summary=r.why_summary,
                curator_total_fit=r.curator_total_fit,
                curator_tier=r.curator_tier,
            ))

        return QueryContext(
            query_id=query_id,
            query_text=q_row.query_text,
            spec_json=spec_json,
            candidates=candidates,
        )


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

def _build_rec_user_prompt(ctx: QueryContext) -> str:
    """Build user prompt for recommendation quality judge (no why text)."""
    spec_str = ""
    if ctx.spec_json:
        spec_parts = []
        for key in ("core_genres", "sub_genres", "core_tone", "key_themes"):
            val = ctx.spec_json.get(key)
            if val:
                spec_parts.append(f"  {key}: {', '.join(val) if isinstance(val, list) else val}")
        if spec_parts:
            spec_str = "\nSpec:\n" + "\n".join(spec_parts)

    titles = []
    for i, c in enumerate(ctx.candidates, 1):
        titles.append(f"{i}. {c.title} (media_id: {c.media_id})")

    return f'User query: "{ctx.query_text}"{spec_str}\n\nRecommendations:\n' + "\n".join(titles)


def _build_expl_user_prompt(ctx: QueryContext) -> str:
    """Build user prompt for explanation quality judge (with why text)."""
    spec_str = ""
    if ctx.spec_json:
        spec_parts = []
        for key in ("core_genres", "sub_genres", "core_tone", "key_themes"):
            val = ctx.spec_json.get(key)
            if val:
                spec_parts.append(f"  {key}: {', '.join(val) if isinstance(val, list) else val}")
        if spec_parts:
            spec_str = "\nSpec:\n" + "\n".join(spec_parts)

    items = []
    for i, c in enumerate(ctx.candidates, 1):
        if c.why_summary:
            items.append(f'{i}. {c.title} (media_id: {c.media_id})\n   Why: {c.why_summary}')

    if not items:
        return ""

    return f'User query: "{ctx.query_text}"{spec_str}\n\nRecommendations with explanations:\n' + "\n".join(items)


# ---------------------------------------------------------------------------
# LLM calls
# ---------------------------------------------------------------------------

async def _judge_recommendations(
    llm: LlmClient, ctx: QueryContext, model: str, semaphore: asyncio.Semaphore
) -> tuple[dict[int, dict], int, int]:
    """Call 1: Score relevance + novelty WITHOUT seeing 'why' text."""
    user_prompt = _build_rec_user_prompt(ctx)
    messages = [
        {"role": "system", "content": REC_JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    async with semaphore:
        resp = await llm.chat(messages=messages, model=model, temperature=0.1)

    content = resp.choices[0].message.content or ""
    usage = resp.usage
    in_tok = usage.prompt_tokens if usage else 0
    out_tok = usage.completion_tokens if usage else 0

    try:
        data = json.loads(content)
        evals = {int(e["media_id"]): e for e in data.get("evaluations", [])}
        logger.debug("Rec judge parsed %d evals for %s", len(evals), ctx.query_id)
    except (json.JSONDecodeError, KeyError, ValueError):
        logger.warning("Failed to parse rec judge response for %s: %s", ctx.query_id, content[:200])
        evals = {}

    return evals, in_tok, out_tok


async def _judge_explanations(
    llm: LlmClient, ctx: QueryContext, model: str, semaphore: asyncio.Semaphore
) -> tuple[dict[int, dict], int, int]:
    """Call 2: Score explanation quality WITH 'why' text."""
    user_prompt = _build_expl_user_prompt(ctx)
    if not user_prompt:
        return {}, 0, 0

    messages = [
        {"role": "system", "content": EXPL_JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    async with semaphore:
        resp = await llm.chat(messages=messages, model=model, temperature=0.1)

    content = resp.choices[0].message.content or ""
    usage = resp.usage
    in_tok = usage.prompt_tokens if usage else 0
    out_tok = usage.completion_tokens if usage else 0

    try:
        data = json.loads(content)
        evals = {int(e["media_id"]): e for e in data.get("evaluations", [])}
    except (json.JSONDecodeError, KeyError, ValueError):
        logger.warning("Failed to parse expl judge response for %s: %s", ctx.query_id, content[:200])
        evals = {}

    return evals, in_tok, out_tok


async def judge_query(
    llm: LlmClient, ctx: QueryContext, model: str, semaphore: asyncio.Semaphore
) -> list[JudgeScore]:
    """Run both judge calls for a query and merge results."""
    (rec_evals, rec_in, rec_out), (expl_evals, expl_in, expl_out) = await asyncio.gather(
        _judge_recommendations(llm, ctx, model, semaphore),
        _judge_explanations(llm, ctx, model, semaphore),
    )

    total_in = rec_in + expl_in
    total_out = rec_out + expl_out

    scores = []
    for c in ctx.candidates:
        rec = rec_evals.get(c.media_id, {})
        expl = expl_evals.get(c.media_id, {})

        scores.append(JudgeScore(
            query_id=ctx.query_id,
            media_id=c.media_id,
            query_text=ctx.query_text,
            title=c.title,
            relevance=rec.get("relevance"),
            novelty=rec.get("novelty"),
            rec_reasoning=rec.get("reasoning"),
            explanation_quality=expl.get("explanation_quality"),
            expl_reasoning=expl.get("reasoning"),
            curator_total_fit=c.curator_total_fit,
            curator_tier=c.curator_tier,
            input_tokens=total_in,
            output_tokens=total_out,
        ))

    return scores


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def upsert_judge_scores(
    engine: Engine,
    scores: list[JudgeScore],
    eval_run_id: str,
    judge_model: str,
) -> None:
    """Upsert judge scores into judge_evaluations table."""
    if not scores:
        return

    with engine.begin() as conn:
        for s in scores:
            conn.execute(
                text("""
                    INSERT INTO judge_evaluations (
                        eval_run_id, query_id, media_id,
                        query_text, title,
                        relevance, novelty, rec_reasoning,
                        explanation_quality, expl_reasoning,
                        curator_total_fit, curator_tier,
                        judge_model, input_tokens, output_tokens
                    ) VALUES (
                        :eval_run_id, :query_id, :media_id,
                        :query_text, :title,
                        :relevance, :novelty, :rec_reasoning,
                        :explanation_quality, :expl_reasoning,
                        :curator_total_fit, :curator_tier,
                        :judge_model, :input_tokens, :output_tokens
                    )
                    ON CONFLICT (eval_run_id, query_id, media_id)
                    DO UPDATE SET
                        relevance = EXCLUDED.relevance,
                        novelty = EXCLUDED.novelty,
                        rec_reasoning = EXCLUDED.rec_reasoning,
                        explanation_quality = EXCLUDED.explanation_quality,
                        expl_reasoning = EXCLUDED.expl_reasoning,
                        created_at = now()
                """),
                {
                    "eval_run_id": eval_run_id,
                    "query_id": s.query_id,
                    "media_id": s.media_id,
                    "query_text": s.query_text,
                    "title": s.title,
                    "relevance": s.relevance,
                    "novelty": s.novelty,
                    "rec_reasoning": s.rec_reasoning,
                    "explanation_quality": s.explanation_quality,
                    "expl_reasoning": s.expl_reasoning,
                    "curator_total_fit": s.curator_total_fit,
                    "curator_tier": s.curator_tier,
                    "judge_model": judge_model,
                    "input_tokens": s.input_tokens,
                    "output_tokens": s.output_tokens,
                },
            )

    logger.info("Upserted %d judge scores (run=%s)", len(scores), eval_run_id)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_judge_summary(all_scores: list[JudgeScore], judge_model: str) -> None:
    """Print formatted summary of judge evaluation results."""
    if not all_scores:
        logger.info("No scores to summarize.")
        return

    relevances = [s.relevance for s in all_scores if s.relevance is not None]
    novelties = [s.novelty for s in all_scores if s.novelty is not None]
    expl_quals = [s.explanation_quality for s in all_scores if s.explanation_quality is not None]

    query_ids = {s.query_id for s in all_scores}
    total_in = sum(s.input_tokens for s in all_scores)
    total_out = sum(s.output_tokens for s in all_scores)
    # Tokens are duplicated per candidate in a query — deduplicate by taking max per query
    token_by_query: dict[str, tuple[int, int]] = {}
    for s in all_scores:
        prev = token_by_query.get(s.query_id, (0, 0))
        token_by_query[s.query_id] = (max(prev[0], s.input_tokens), max(prev[1], s.output_tokens))
    total_in = sum(v[0] for v in token_by_query.values())
    total_out = sum(v[1] for v in token_by_query.values())

    print(f"\n{'=' * 60}")
    print(f"  Reelix Judge Evaluation")
    print(f"  {len(query_ids)} queries, {len(all_scores)} candidates evaluated")
    print(f"{'=' * 60}")

    if relevances:
        avg_rel = sum(relevances) / len(relevances)
        avg_nov = sum(novelties) / len(novelties) if novelties else 0
        print(f"\n  [RECOMMENDATION QUALITY] (evaluates curator)")
        print(f"    Avg Relevance                       {avg_rel:.1f} / 5")
        print(f"    Avg Novelty                         {avg_nov:.1f} / 5")

    if expl_quals:
        avg_expl = sum(expl_quals) / len(expl_quals)
        print(f"\n  [EXPLANATION QUALITY] (evaluates explanation agent)")
        print(f"    Avg Explanation Quality              {avg_expl:.1f} / 5")

    # Curator agreement
    paired = [(s.relevance, s.curator_total_fit) for s in all_scores
              if s.relevance is not None and s.curator_total_fit is not None]
    if len(paired) >= 5:
        # Group by curator tier
        tier_relevances: dict[str, list[int]] = {}
        for s in all_scores:
            if s.relevance is not None and s.curator_tier:
                tier_relevances.setdefault(s.curator_tier, []).append(s.relevance)

        print(f"\n  [CURATOR AGREEMENT]")
        for tier in ("strong_match", "moderate_match", "no_match"):
            vals = tier_relevances.get(tier, [])
            if vals:
                avg = sum(vals) / len(vals)
                label = tier.replace("_", " ").title()
                print(f"    {label} avg relevance          {avg:.1f} / 5")

    print(f"\n  [COST]")
    print(f"    Total tokens                        {total_in + total_out:,}")
    print(f"    Judge model                         {judge_model}")
    print(f"\n{'=' * 60}\n")
