"""
Unified LLM client — async (chat / chat_stream) and sync (stream) wrappers
around the OpenAI Chat Completions API.

The async methods emit OpenTelemetry spans (`llm.chat`, `llm.chat_stream`) with
GenAI semantic-convention attributes plus a Reelix-specific `reelix.agent.role`.
OTel is treated as a no-op when no TracerProvider is configured (e.g. in the
data-pipeline eval jobs), so this module stays importable everywhere.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import AsyncIterator, Iterator
from typing import Any, Optional

from openai import AsyncOpenAI, OpenAI
from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.trace import Span, SpanKind, Status, StatusCode

# ── GenAI semantic-convention attribute keys ──────────────────────────
# Plain string literals (rather than the opentelemetry-semantic-conventions
# package) so reelix-core needs only opentelemetry-api — keeping the
# data-pipeline venv lean. These keys are stable across the GenAI conventions.
_GEN_AI_SYSTEM = "gen_ai.system"
_GEN_AI_OPERATION_NAME = "gen_ai.operation.name"
_GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
_GEN_AI_REQUEST_TEMPERATURE = "gen_ai.request.temperature"
_GEN_AI_REQUEST_MAX_TOKENS = "gen_ai.request.max_tokens"
_GEN_AI_REQUEST_TOP_P = "gen_ai.request.top_p"
_GEN_AI_RESPONSE_ID = "gen_ai.response.id"
_GEN_AI_RESPONSE_MODEL = "gen_ai.response.model"
_GEN_AI_RESPONSE_FINISH_REASONS = "gen_ai.response.finish_reasons"
_GEN_AI_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
_GEN_AI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
_REELIX_AGENT_ROLE = "reelix.agent.role"

_tracer = trace.get_tracer("reelix_core.llm_client")


def _record_prompts_enabled() -> bool:
    """Whether to attach prompt/completion content to spans.

    Off by default. Prompt/completion text can carry user PII, so it is only
    recorded when ``REELIX_OTEL_RECORD_PROMPTS`` is truthy — and then as span
    *events* (handled/sampled separately), never as span attributes.
    """
    return os.getenv("REELIX_OTEL_RECORD_PROMPTS", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _set_request_attrs(
    span: Span,
    *,
    operation: str,
    kwargs: dict[str, Any],
    agent_role: str | None,
) -> None:
    """Set gen_ai request attributes from the kwargs actually sent to OpenAI."""
    span.set_attribute(_GEN_AI_SYSTEM, "openai")
    span.set_attribute(_GEN_AI_OPERATION_NAME, operation)
    if kwargs.get("model"):
        span.set_attribute(_GEN_AI_REQUEST_MODEL, kwargs["model"])
    if kwargs.get("temperature") is not None:
        span.set_attribute(_GEN_AI_REQUEST_TEMPERATURE, kwargs["temperature"])
    if kwargs.get("max_tokens") is not None:
        span.set_attribute(_GEN_AI_REQUEST_MAX_TOKENS, kwargs["max_tokens"])
    if kwargs.get("top_p") is not None:
        span.set_attribute(_GEN_AI_REQUEST_TOP_P, kwargs["top_p"])
    if agent_role:
        span.set_attribute(_REELIX_AGENT_ROLE, agent_role)


def _set_usage_attrs(span: Span, usage: Any) -> None:
    if usage is None:
        return
    prompt_tokens = getattr(usage, "prompt_tokens", None)
    completion_tokens = getattr(usage, "completion_tokens", None)
    if prompt_tokens is not None:
        span.set_attribute(_GEN_AI_USAGE_INPUT_TOKENS, prompt_tokens)
    if completion_tokens is not None:
        span.set_attribute(_GEN_AI_USAGE_OUTPUT_TOKENS, completion_tokens)


def _set_response_attrs(span: Span, resp: Any) -> None:
    """Set gen_ai response attributes from a non-streaming completion object."""
    resp_id = getattr(resp, "id", None)
    if resp_id:
        span.set_attribute(_GEN_AI_RESPONSE_ID, resp_id)
    resp_model = getattr(resp, "model", None)
    if resp_model:
        span.set_attribute(_GEN_AI_RESPONSE_MODEL, resp_model)

    choices = getattr(resp, "choices", None) or []
    finish_reasons = [
        getattr(c, "finish_reason", None)
        for c in choices
        if getattr(c, "finish_reason", None)
    ]
    if finish_reasons:
        span.set_attribute(_GEN_AI_RESPONSE_FINISH_REASONS, finish_reasons)

    _set_usage_attrs(span, getattr(resp, "usage", None))


def _record_prompt_event(span: Span, messages: list[dict[str, Any]]) -> None:
    if not _record_prompts_enabled():
        return
    try:
        payload = json.dumps(messages, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        payload = str(messages)
    span.add_event("gen_ai.content.prompt", attributes={"gen_ai.prompt": payload})


def _record_completion_event(span: Span, completion: str | None) -> None:
    if not _record_prompts_enabled() or not completion:
        return
    span.add_event(
        "gen_ai.content.completion",
        attributes={"gen_ai.completion": completion},
    )


class LlmClient:
    """
    Thin wrapper around OpenAI's chat completion API.

    Async methods (chat, chat_stream) use AsyncOpenAI.
    Sync method (stream) uses OpenAI — lazily initialised on first call.
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        timeout: float | None = 20.0,
        api_key: str | None = None,
        max_retries: int = 2,
    ) -> None:
        client_kwargs: dict = {"timeout": timeout}
        if api_key is not None:
            client_kwargs["api_key"] = api_key

        self._async_client = AsyncOpenAI(**client_kwargs)
        self._default_model = model
        self._max_retries = max_retries

        # Lazy-init: only created when stream() is called
        self._sync_client: OpenAI | None = None
        self._sync_client_kwargs = client_kwargs

    def _get_sync_client(self) -> OpenAI:
        if self._sync_client is None:
            self._sync_client = OpenAI(**self._sync_client_kwargs)
        return self._sync_client

    # ── Async: non-streaming ──────────────────────────────────────────

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
        agent_role: Optional[str] = None,
    ):
        """
        Call the OpenAI chat completion endpoint with optional tools.

        Returns the raw OpenAI response object.

        ``agent_role`` (orchestrator / curator / reflection / …) tags the span
        with ``reelix.agent.role`` so the agent loop is legible in Tempo.
        """
        kwargs: dict[str, Any] = dict(
            model=model or self._default_model,
            messages=messages,
            temperature=temperature,
        )

        if tools is not None:
            kwargs["tools"] = tools
            if tool_choice is not None:
                kwargs["tool_choice"] = tool_choice

        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        if extra_args:
            kwargs.update(extra_args)

        with _tracer.start_as_current_span("llm.chat", kind=SpanKind.CLIENT) as span:
            _set_request_attrs(
                span, operation="chat", kwargs=kwargs, agent_role=agent_role
            )
            _record_prompt_event(span, messages)
            try:
                resp = await self._async_client.chat.completions.create(**kwargs)
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                raise

            _set_response_attrs(span, resp)
            try:
                _record_completion_event(span, resp.choices[0].message.content)
            except (AttributeError, IndexError):
                pass
            return resp

    # ── Async: streaming ──────────────────────────────────────────────

    async def chat_stream(
        self,
        *,
        messages: list[dict[str, Any]],
        model: Optional[str] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[str] = "auto",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        extra_args: Optional[dict[str, Any]] = None,
        include_usage: bool = False,
        top_p: float = 1.0,
        agent_role: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """
        Stream content deltas from the OpenAI chat completion endpoint.

        Yields strings (content deltas) suitable for SSE streaming.

        The ``llm.chat_stream`` span stays open for the whole stream and ends
        when the generator is exhausted/closed. It is made current only while
        the request is initiated (so the auto-instrumented httpx span parents
        under it) — not across yields, which would otherwise leak this context
        into the caller's SSE send spans.
        """
        kwargs: dict[str, Any] = dict(
            model=model or self._default_model,
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            stream=True,
        )

        if include_usage:
            kwargs["stream_options"] = {"include_usage": True}

        if tools is not None:
            kwargs["tools"] = tools
            if tool_choice is not None:
                kwargs["tool_choice"] = tool_choice

        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        if extra_args:
            kwargs.update(extra_args)

        span = _tracer.start_span("llm.chat_stream", kind=SpanKind.CLIENT)
        _set_request_attrs(
            span, operation="chat_stream", kwargs=kwargs, agent_role=agent_role
        )
        _record_prompt_event(span, messages)

        record_completion = _record_prompts_enabled()
        completion_parts: list[str] = []
        finish_reasons: list[str] = []
        usage: Any = None

        try:
            # Span current only around request initiation, so the httpx request
            # span parents under llm.chat_stream. Detach before iterating.
            token = otel_context.attach(trace.set_span_in_context(span))
            try:
                stream = await self._async_client.chat.completions.create(**kwargs)
            finally:
                otel_context.detach(token)

            async for chunk in stream:
                chunk_usage = getattr(chunk, "usage", None)
                if chunk_usage is not None:
                    usage = chunk_usage

                choices = getattr(chunk, "choices", None)
                if not choices:
                    continue

                finish_reason = getattr(choices[0], "finish_reason", None)
                if finish_reason:
                    finish_reasons.append(finish_reason)

                delta = getattr(choices[0], "delta", None)
                if not delta:
                    continue

                content = getattr(delta, "content", None)
                if content:
                    if record_completion:
                        completion_parts.append(content)
                    yield content

            if finish_reasons:
                span.set_attribute(_GEN_AI_RESPONSE_FINISH_REASONS, finish_reasons)
            _set_usage_attrs(span, usage)
            if record_completion:
                _record_completion_event(span, "".join(completion_parts))
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
        finally:
            span.end()

    # ── Sync: streaming (with retry) ──────────────────────────────────

    def stream(
        self,
        messages: list,
        model: str | None = None,
        **params: Any,
    ) -> Iterator[str]:
        """
        Synchronous streaming generator with retry logic.

        Yields content delta strings. Retries up to max_retries on failure.
        """
        call_params = params or {"temperature": 0.7, "top_p": 1.0}
        client = self._get_sync_client()

        for attempt in range(self._max_retries + 1):
            try:
                response = client.chat.completions.create(
                    model=model or self._default_model,
                    messages=messages,
                    stream=True,
                    **call_params,
                )

                for chunk in response:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield delta
                return
            except Exception:
                if attempt >= self._max_retries:
                    raise
                time.sleep(0.5 * (2**attempt))