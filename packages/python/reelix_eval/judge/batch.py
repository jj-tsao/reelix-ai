"""Batch API path for the judge — half price, for the nightly job.

Judging a day of traffic is offline work with no latency requirement, which is
exactly what the Message Batches API is for: identical requests at 50% of the
standard token price. Most batches finish well inside an hour.

**Not a drop-in replacement for the synchronous path.** The Investigator's
`run_judge` tool needs answers inside a turn, so it keeps using
`runner.judge_queries`. This module is for `jobs.eval_judge`, where waiting is
free. Both share `runner.merge_verdicts`, so their output can't drift.

Batch requests can't use `messages.parse()`, so the schema is attached manually
via `output_config.format` and the response text is validated client-side against
the same pydantic models — the guarantee is preserved, just enforced one step
later.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from reelix_eval.judge.prompts import (
    EXPL_JUDGE_SYSTEM,
    REC_JUDGE_SYSTEM,
    build_expl_prompt,
    build_rec_prompt,
)
from reelix_eval.judge.runner import JudgeConfig, QueryJudgement, merge_verdicts
from reelix_eval.judge.schema import ExplanationQualityVerdict, RecQualityVerdict

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic

    from reelix_eval.store import QueryDetail

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL = 30.0
DEFAULT_TIMEOUT = 3600.0 * 2


def _json_schema(model: type) -> dict[str, Any]:
    """Pydantic model → the API's expected JSON schema shape.

    Uses the SDK's own transform (what `messages.parse` calls internally) so the
    batch path and the synchronous path send an identical schema. Falls back to
    bare pydantic if that private helper ever moves.
    """
    try:
        from anthropic.lib._parse._transform import transform_schema

        return transform_schema(model)
    except Exception:  # pragma: no cover - defensive
        logger.warning("SDK schema transform unavailable; using raw pydantic schema")
        return model.model_json_schema()


def _params(system: str, prompt: str, model_cls: type, cfg: JudgeConfig) -> dict:
    params: dict[str, Any] = {
        "model": cfg.model,
        "max_tokens": cfg.max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
        "output_config": {
            "format": {"type": "json_schema", "schema": _json_schema(model_cls)}
        },
    }
    # request_kwargs() carries effort; merge it into the same output_config so we
    # don't clobber the format we just set.
    extra = cfg.request_kwargs()
    if "output_config" in extra:
        params["output_config"].update(extra["output_config"])
    return params


@dataclass
class BatchSubmission:
    batch_id: str
    #: custom_id → (query_id, "rec" | "expl")
    routing: dict[str, tuple[str, str]] = field(default_factory=dict)

    @property
    def request_count(self) -> int:
        return len(self.routing)


async def submit(
    client: "AsyncAnthropic",
    details: list["QueryDetail"],
    cfg: JudgeConfig | None = None,
) -> BatchSubmission:
    """Queue every judge call for `details` as one batch."""
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    cfg = cfg or JudgeConfig()
    requests: list[Request] = []
    routing: dict[str, tuple[str, str]] = {}

    # Index-based custom_ids: query_ids contain characters and lengths the field
    # doesn't accept, so route through a local map instead.
    for idx, d in enumerate(details):
        rec_id = f"q{idx}-rec"
        routing[rec_id] = (d.query_id, "rec")
        requests.append(
            Request(
                custom_id=rec_id,
                params=MessageCreateParamsNonStreaming(
                    **_params(
                        REC_JUDGE_SYSTEM, build_rec_prompt(d), RecQualityVerdict, cfg
                    )
                ),
            )
        )

        expl_prompt = build_expl_prompt(d)
        if not expl_prompt:
            continue  # no "why" text logged — skip rather than score its absence
        expl_id = f"q{idx}-expl"
        routing[expl_id] = (d.query_id, "expl")
        requests.append(
            Request(
                custom_id=expl_id,
                params=MessageCreateParamsNonStreaming(
                    **_params(
                        EXPL_JUDGE_SYSTEM,
                        expl_prompt,
                        ExplanationQualityVerdict,
                        cfg,
                    )
                ),
            )
        )

    batch = await client.messages.batches.create(requests=requests)
    logger.info(
        "Submitted batch %s — %d requests for %d queries",
        batch.id,
        len(requests),
        len(details),
    )
    return BatchSubmission(batch_id=batch.id, routing=routing)


async def wait(
    client: "AsyncAnthropic",
    batch_id: str,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    """Poll until the batch ends. Returns the terminal processing status."""
    waited = 0.0
    while True:
        batch = await client.messages.batches.retrieve(batch_id)
        if batch.processing_status == "ended":
            logger.info("Batch %s ended: %s", batch_id, batch.request_counts)
            return batch.processing_status
        if waited >= timeout:
            raise TimeoutError(
                f"Batch {batch_id} still {batch.processing_status} after {timeout:.0f}s"
            )
        await asyncio.sleep(poll_interval)
        waited += poll_interval


async def collect(
    client: "AsyncAnthropic",
    submission: BatchSubmission,
    details: list["QueryDetail"],
    cfg: JudgeConfig | None = None,
) -> list[QueryJudgement]:
    """Read a finished batch back and merge it into per-query judgements."""
    cfg = cfg or JudgeConfig()
    by_query = {d.query_id: d for d in details}

    verdicts: dict[str, dict[str, Any]] = {
        qid: {"rec": None, "expl": None, "in": 0, "out": 0, "status": "ok"}
        for qid in by_query
    }

    async for result in await client.messages.batches.results(submission.batch_id):
        route = submission.routing.get(result.custom_id)
        if not route:
            logger.warning("Unrecognised custom_id %s", result.custom_id)
            continue
        qid, kind = route
        slot = verdicts[qid]

        # Results arrive in any order and each carries its own outcome — key by
        # custom_id, never by position.
        if result.result.type != "succeeded":
            logger.warning(
                "Batch item %s (%s): %s", result.custom_id, qid, result.result.type
            )
            slot["status"] = "error"
            continue

        msg = result.result.message
        slot["in"] += msg.usage.input_tokens or 0
        slot["out"] += msg.usage.output_tokens or 0

        if msg.stop_reason == "refusal":
            slot["status"] = "refused"
            continue

        text = next((b.text for b in msg.content if b.type == "text"), None)
        if not text:
            slot["status"] = "error"
            continue

        model_cls = RecQualityVerdict if kind == "rec" else ExplanationQualityVerdict
        try:
            slot[kind] = model_cls.model_validate_json(text)
        except Exception as e:
            # Same guarantee as messages.parse(), enforced one step later: a
            # malformed verdict is an error, never a silently empty score set.
            logger.error("Schema validation failed for %s: %s", result.custom_id, e)
            slot["status"] = "error"

    return [
        merge_verdicts(
            by_query[qid],
            rec=slot["rec"],
            expl=slot["expl"],
            input_tokens=slot["in"],
            output_tokens=slot["out"],
            status=slot["status"],
        )
        for qid, slot in verdicts.items()
    ]


async def judge_queries_batch(
    client: "AsyncAnthropic",
    details: list["QueryDetail"],
    cfg: JudgeConfig | None = None,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    timeout: float = DEFAULT_TIMEOUT,
) -> list[QueryJudgement]:
    """Submit → wait → collect. Half the cost of `judge_queries`, minutes slower."""
    cfg = cfg or JudgeConfig()
    if not details:
        return []

    submission = await submit(client, details, cfg)
    await wait(client, submission.batch_id, poll_interval, timeout)
    return await collect(client, submission, details, cfg)