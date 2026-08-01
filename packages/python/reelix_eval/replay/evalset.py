"""Frozen eval sets — reproducible inputs for curator replay.

A snapshot freezes real production queries together with the candidates the
pipeline retrieved for them and the results it produced. Because the candidates
are frozen, a replay needs no Qdrant, no torch, and no cross-encoder — it is
deterministic apart from the curator LLM itself, which is the thing under test.

The baseline block records what production actually did, so an A/B after a prompt
edit compares against real behaviour rather than a re-derived guess.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.engine import Engine

from reelix_eval.store import get_query_detail

logger = logging.getLogger(__name__)

#: Snapshot format version. Bump when the on-disk shape changes so a stale eval
#: set fails loudly instead of replaying against mismatched fields.
EVALSET_VERSION = 1


@dataclass
class FrozenCandidate:
    media_id: int
    title: str
    llm_context: dict | None
    genres: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    overview: str = ""
    release_year: int | None = None
    watch_providers: list[str] = field(default_factory=list)
    # What production's curator decided about this candidate.
    baseline_genre_fit: int | None = None
    baseline_tone_fit: int | None = None
    baseline_theme_fit: int | None = None
    baseline_total_fit: int | None = None
    baseline_tier: str | None = None
    baseline_is_served: bool = False
    baseline_rank: int | None = None


@dataclass
class EvalCase:
    query_id: str
    query_text: str
    spec_json: dict | None
    candidates: list[FrozenCandidate]
    baseline_tier_stats: dict | None = None
    baseline_served_ids: list[int] = field(default_factory=list)

    @property
    def has_llm_context(self) -> bool:
        """Whether every candidate carries the card the curator prompt needs."""
        return all(c.llm_context for c in self.candidates)


def evalset_path(name: str, root: Path | str) -> Path:
    return Path(root) / f"{name}.jsonl"


def snapshot(
    engine: Engine,
    query_ids: list[str],
    name: str,
    root: Path | str,
) -> Path:
    """Freeze `query_ids` into `<root>/<name>.jsonl`.

    Skips queries whose candidates can't be resolved (missing rows, or Qdrant
    payloads that no longer carry `llm_context`) rather than writing a case the
    replay can't run.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    out = evalset_path(name, root)

    cases: list[EvalCase] = []
    skipped: list[str] = []

    for qid in query_ids:
        detail = get_query_detail(
            engine, qid, backfill_payloads=True, served_only=False
        )
        if not detail or not detail.candidates:
            skipped.append(qid)
            continue

        frozen = [
            FrozenCandidate(
                media_id=c.media_id,
                title=c.title,
                llm_context=c.llm_context,
                genres=c.genres,
                keywords=c.keywords,
                overview=c.overview,
                release_year=c.release_year,
                watch_providers=c.watch_providers,
                baseline_genre_fit=c.genre_fit,
                baseline_tone_fit=c.tone_fit,
                baseline_theme_fit=c.theme_fit,
                baseline_total_fit=c.total_fit,
                baseline_tier=c.tier,
                baseline_is_served=c.is_served,
                baseline_rank=c.final_rank,
            )
            for c in detail.candidates
        ]

        case = EvalCase(
            query_id=detail.query_id,
            query_text=detail.query_text,
            spec_json=detail.spec_json,
            candidates=frozen,
            baseline_tier_stats=detail.tier_stats,
            baseline_served_ids=[c.media_id for c in detail.served],
        )

        if not case.has_llm_context:
            logger.warning(
                "Skipping %s — candidates missing llm_context (re-index needed?)", qid
            )
            skipped.append(qid)
            continue

        cases.append(case)

    header: dict[str, Any] = {
        "_meta": {
            "version": EVALSET_VERSION,
            "name": name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "cases": len(cases),
            "skipped": skipped,
        }
    }

    with out.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(header, ensure_ascii=False) + "\n")
        for case in cases:
            fh.write(json.dumps(asdict(case), ensure_ascii=False) + "\n")

    logger.info(
        "Snapshot %s: %d cases, %d skipped → %s", name, len(cases), len(skipped), out
    )
    return out


def load(path: Path | str) -> list[EvalCase]:
    """Read an eval set back. Raises on a version mismatch."""
    path = Path(path)
    with path.open(encoding="utf-8") as fh:
        lines = [line for line in fh if line.strip()]

    if not lines:
        raise ValueError(f"Empty eval set: {path}")

    meta = json.loads(lines[0]).get("_meta", {})
    version = meta.get("version")
    if version != EVALSET_VERSION:
        raise ValueError(
            f"Eval set {path} is version {version}, expected {EVALSET_VERSION}. "
            "Re-snapshot it."
        )

    cases: list[EvalCase] = []
    for line in lines[1:]:
        raw = json.loads(line)
        raw["candidates"] = [FrozenCandidate(**c) for c in raw["candidates"]]
        cases.append(EvalCase(**raw))

    return cases