"""Curator-only replay with strict output validity and revision-attested workers.

`replay` executes a frozen production-source snapshot in a fresh interpreter.
`replay_case` is the local/offline seam and has no loaded-revision attestation.
Neither successful execution nor slate overlap establishes fix effectiveness.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from reelix_eval.verification import RevisionEvidence
import hashlib
from dataclasses import asdict
from pathlib import Path

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
    execution_completed: bool = False
    outputs_valid: bool = False

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
    revision: RevisionEvidence | None = None
    evalset_sha256: str = ""
    execution_completed: bool = False
    issues: list[str] = field(default_factory=list)

    @property
    def ok_cases(self) -> list[CaseReplay]:
        return [c for c in self.cases if c.ok and c.execution_completed and c.outputs_valid]

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
            "aggregate_cases": len(ok),
            "overlap_cases": len(overlaps),
            "failed_case_ids": [c.query_id for c in self.cases if c not in ok],
            "execution_completed": self.execution_completed,
            "revision": asdict(self.revision) if self.revision else None,
            "revision_matched": bool(self.revision and self.revision.matched),
            "evalset_sha256": self.evalset_sha256,
            "issues": self.issues,
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
            "total_input_tokens": sum(c.input_tokens for c in self.cases),
            "total_output_tokens": sum(c.output_tokens for c in self.cases),
        }


def _to_candidates(case: "EvalCase") -> list:
    """Rebuild the `Candidate` objects the curator prompt builder expects."""
    from reelix_ranking.types import Candidate
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


def cases_digest(cases) -> str:
    return hashlib.sha256(json.dumps([asdict(c) for c in cases], sort_keys=True,
                                     allow_nan=False).encode()).hexdigest()


def _to_spec(case):
    from reelix_agent.core.types import RecQuerySpec
    if not isinstance(case.spec_json, dict):
        raise ValueError('missing_spec')
    raw = dict(case.spec_json)
    raw.setdefault('query_text', case.query_text)
    return RecQuerySpec(**raw)  # No fallback that could silently discard constraints.


class _RecordingClient:
    def __init__(self, client):
        self.client = client
        self.input_tokens = self.output_tokens = self.calls = 0

    async def chat(self, **kwargs):
        response = await self.client.chat(**kwargs)
        self.calls += 1
        usage = getattr(response, 'usage', None)
        self.input_tokens += getattr(usage, 'prompt_tokens', 0) or 0
        self.output_tokens += getattr(usage, 'completion_tokens', 0) or 0
        choices = getattr(response, 'choices', None)
        if not choices or getattr(choices[0], 'finish_reason', None) != 'stop':
            raise ValueError('incomplete_model_response')
        if getattr(choices[0].message, 'refusal', None):
            raise ValueError('model_refusal')
        return response


def _validate_output(content, expected_ids):
    def reject_constant(_): raise ValueError('nonfinite_output')
    def unique_fields(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError('duplicate_output_fields')
            result[key] = value
        return result
    data = json.loads(content, parse_constant=reject_constant, object_pairs_hook=unique_fields)
    if not isinstance(data, dict) or not isinstance(data.get('evaluation_results'), list):
        raise ValueError('invalid_output_structure')
    rows = data['evaluation_results']
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or type(row.get('media_id')) is not int:
            raise ValueError('invalid_evaluation_id')
        mid = row['media_id']
        if mid in seen or mid not in expected_ids:
            raise ValueError('duplicate_or_unexpected_id')
        seen.add(mid)
        for name in ('genre_fit', 'tone_fit', 'theme_fit'):
            if type(row.get(name)) is not int or row[name] not in (0, 1, 2):
                raise ValueError('invalid_required_score')
        if row.get('structure_fit', 0) != 0:
            raise ValueError('unexpected_structure_score')
    if seen != expected_ids:
        raise ValueError('incomplete_candidate_coverage')
    return rows


async def replay_case(case, llm_client, semaphore=None) -> CaseReplay:
    """Local evaluation seam. Only fresh-process replay adds revision evidence."""
    result = CaseReplay(query_id=case.query_id, query_text=case.query_text, ok=False,
                        baseline_served_ids=list(case.baseline_served_ids),
                        baseline_tier_stats=dict(case.baseline_tier_stats or {}))
    try:
        ids = [c.media_id for c in case.candidates]
        if not ids or any(type(i) is not int for i in ids) or len(ids) != len(set(ids)):
            raise ValueError('invalid_candidate_ids')
        if not case.has_llm_context or not set(case.baseline_served_ids) <= set(ids):
            raise ValueError('invalid_frozen_inputs')
        candidates, spec = _to_candidates(case), _to_spec(case)
    except Exception:
        result.error = 'invalid_frozen_inputs_or_spec'
        return result
    # Imported only inside the executing interpreter. A parent local call remains
    # explicitly unattested; production verification always uses replay().
    from reelix_agent.curator.curator_agent import run_curator_agent
    from reelix_agent.curator.curator_tiers import apply_curator_tiers
    mid = len(candidates) // CURATOR_BATCHES
    batches = [b for b in (candidates[:mid], candidates[mid:]) if b]
    sem = semaphore or asyncio.Semaphore(DEFAULT_CONCURRENCY)
    recorder = _RecordingClient(llm_client)
    async def evaluate(batch):
        async with sem:
            return await run_curator_agent(query_text=spec.query_text, spec=spec,
                candidates=batch, llm_client=recorder, user_signals=None)
    outputs = await asyncio.gather(*(evaluate(b) for b in batches), return_exceptions=True)
    result.input_tokens, result.output_tokens = recorder.input_tokens, recorder.output_tokens
    if any(isinstance(o, BaseException) for o in outputs):
        result.error = 'curator_execution_failed'
        return result
    result.execution_completed = True
    evaluations = []
    try:
        for batch, (content, usage) in zip(batches, outputs):
            evaluations.extend(_validate_output(content, {int(c.id) for c in batch}))
        final, stats = apply_curator_tiers(evaluation_results=evaluations, candidates=candidates,
                                          limit=spec.num_recs or 8)
    except Exception:
        result.error = 'malformed_or_incomplete_curator_output'
        return result
    result.outputs_valid = result.ok = True
    result.served_ids, result.tier_stats = [int(c.id) for c in final], stats
    result.fits = {int(c.id): {d: c.payload.get('curator_'+d) for d in
                   ('genre_fit', 'tone_fit', 'theme_fit', 'total_fit', 'category')} for c in candidates}
    return result


async def _replay_local(cases, llm_client, label, concurrency):
    sem = asyncio.Semaphore(concurrency)
    results = await asyncio.gather(*(replay_case(c, llm_client, sem) for c in cases))
    return ReplayRun(label=label, cases=list(results), evalset_sha256=cases_digest(cases),
                     execution_completed=bool(cases) and all(c.execution_completed for c in results))


async def replay(cases, llm_client, label='working-tree', concurrency=DEFAULT_CONCURRENCY,
                 *, source_root: Path | None = None, expected_revision: str | None = None,
                 timeout: float = 300.0) -> ReplayRun:
    """Fresh-process source snapshot. Caller retains its client and credentials.

    Baseline/control runs must be explicitly requested before editing (or use an
    explicitly supplied prior source tree). No extra paid calls are implicit.
    """
    from reelix_eval.replay.isolated import replay_fresh
    return await replay_fresh(cases, llm_client, label, concurrency, source_root,
                              expected_revision, timeout)
