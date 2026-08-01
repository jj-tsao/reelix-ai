from reelix_core.types import UserSignals
from reelix_ranking.types import Candidate
from reelix_core.llm_client import LlmClient
from reelix_agent.core.llm import LlmUsage
from reelix_agent.core.types import RecQuerySpec

from .curator_prompts import CURATOR_PROMPT_S, build_curator_user_prompt

CURATOR_MODEL = "gpt-4.1-mini"


async def run_curator_agent(
    *,
    query_text: str,
    spec: RecQuerySpec,
    candidates: list[Candidate],
    llm_client: LlmClient,
    user_signals: UserSignals | None = None,
) -> tuple[str, LlmUsage]:
    """Evaluate a batch of candidates.

    Returns (raw JSON content, token usage) so callers can accumulate real
    per-call usage into the request trace instead of guessing.
    """
    system_msg = {
        "role": "system",
        "content": CURATOR_PROMPT_S,
    }

    user_prompt = build_curator_user_prompt(
        candidates=candidates,
        query_text=query_text,
        spec=spec,
        user_signals=user_signals,
    )

    user_msg = {"role": "user", "content": user_prompt}

    resp = await llm_client.chat(
        messages=[system_msg, user_msg],
        tools=None,
        tool_choice=None,
        temperature=0.1,
        model=CURATOR_MODEL,
        agent_role="curator",
    )

    content = resp.choices[0].message.content

    usage = getattr(resp, "usage", None)
    llm_usage = LlmUsage(
        input_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
        output_tokens=getattr(usage, "completion_tokens", None) if usage else None,
        model=CURATOR_MODEL,
    )

    return content, llm_usage
