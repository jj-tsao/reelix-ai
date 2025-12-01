from __future__ import annotations

from typing import Any, Optional

from openai import AsyncOpenAI


class LlmClient:
    """
    Thin async wrapper around OpenAI's chat completion API.
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",  # default model
        timeout: float | None = 20.0,
        api_key: str | None = None,
    ) -> None:
        # Reads OPENAI_API_KEY from env by default
        client_kwargs: dict = {"timeout": timeout}
        if api_key is not None:
            client_kwargs["api_key"] = api_key
        
        self._client = AsyncOpenAI(**client_kwargs)
        self._default_model = model

    async def chat(
        self,
        *,
        messages: list[dict[str, Any]],
        model: Optional[str] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[str] = "auto",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        extra_args: Optional[dict[str, Any]] = None,
    ):
        """
        Call the OpenAI chat completion endpoint with optional tools.

        Returns:
            The raw OpenAI response object.
            - You can access resp.choices[0].message, resp.usage, etc.
        """
        kwargs: dict[str, Any] = dict(
            model=model or self._default_model,
            messages=messages,
            temperature=temperature,
        )

        if tools is not None:
            kwargs["tools"] = tools
            # "auto" | "none" | {"type": "function", "function": {"name": "..."}}
            if tool_choice is not None:
                kwargs["tool_choice"] = tool_choice

        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        if extra_args:
            kwargs.update(extra_args)

        # Using Chat Completions API with tools
        resp = await self._client.chat.completions.create(**kwargs)
        return resp
