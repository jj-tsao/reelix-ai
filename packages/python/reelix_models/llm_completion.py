from __future__ import annotations

import time
from typing import List, cast

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam
from reelix_core.config import CHAT_COMPLETION_MODEL


class OpenAIChatLLM:
    def __init__(
        self, client: OpenAI, *, request_timeout: float = 60.0, max_retries: int = 2
    ):
        self.client = client
        self.request_timeout = request_timeout
        self.max_retries = max_retries

    def _build_chat_history(
        self, history: list, max_turns: int = 5
    ) -> List[ChatCompletionMessageParam]:
        if not history:
            return []
        msgs: List[ChatCompletionMessageParam] = []
        # If history items are custom objects, coerce to dicts:
        for h in history[-max_turns * 2 :]:
            role = getattr(h, "role", None) or h.get("role")
            content = getattr(h, "content", None) or h.get("content")
            if role in ("system", "user", "assistant") and isinstance(content, str):
                msgs.append(
                    {
                        "role": cast(ChatCompletionMessageParam["role"], role),
                        "content": content,
                    }
                )
        return msgs

    def stream_chat(
        self, history, system_prompt: str, user_message: str, temperature: float = 0.7
    ):
        messages: List[ChatCompletionMessageParam] = []
        messages.append({"role": "system", "content": system_prompt})
        messages += self._build_chat_history(history or [])
        messages.append({"role": "user", "content": user_message})
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=CHAT_COMPLETION_MODEL,
                    messages=messages,
                    stream=True,
                    temperature=temperature,
                )

                for chunk in response:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield delta
                return
            except Exception:
                if attempt >= self.max_retries:
                    raise
                time.sleep(0.5 * (2**attempt))

    def chat(
        self, history, system_prompt: str, user_message: str, temperature: float = 0.7
    ):
        messages: List[ChatCompletionMessageParam] = []
        messages.append({"role": "system", "content": system_prompt})
        messages += self._build_chat_history(history or [])
        messages.append({"role": "user", "content": user_message})
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=OPENAI_MODEL,
                    messages=messages,
                    temperature=temperature,
                )
                return response.choices[0].message.content or ""
            except Exception:
                if attempt >= self.max_retries:
                    raise
                time.sleep(0.5 * (2**attempt))
