"""LLM-as-judge for Reelix recommendations, built on the Anthropic SDK.

Two independent calls per query keep the curator and the explanation agent
separable: recommendation quality is judged *without* the "why" text, explanation
quality *with* it.

The judge calls the raw Messages API rather than running as an Agent SDK
subagent, so it can use `messages.parse()`'s schema guarantee and so the batch
`jobs.eval_judge` path works with no agent involved.
"""

from reelix_eval.judge.batch import judge_queries_batch
from reelix_eval.judge.runner import (
    DEFAULT_JUDGE_MODEL,
    JUDGE_KEY_ENV,
    ItemJudgement,
    JudgeConfig,
    QueryJudgement,
    build_client,
    judge_queries,
    judge_query,
    merge_verdicts,
    persist,
    summarize,
)
from reelix_eval.judge.schema import (
    ExplanationQualityVerdict,
    RecQualityVerdict,
)
from reelix_eval.judge.spec_check import check_spec_violation

__all__ = [
    "DEFAULT_JUDGE_MODEL",
    "JUDGE_KEY_ENV",
    "ExplanationQualityVerdict",
    "build_client",
    "ItemJudgement",
    "JudgeConfig",
    "QueryJudgement",
    "RecQualityVerdict",
    "check_spec_violation",
    "judge_queries",
    "judge_queries_batch",
    "judge_query",
    "merge_verdicts",
    "persist",
    "summarize",
]