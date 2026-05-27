from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

from opentelemetry import context as otel_context

_T = TypeVar("_T")


def traced_create_task(
    coro: Coroutine[Any, Any, _T],
    *,
    name: str | None = None,
) -> asyncio.Task[_T]:
    """Schedule ``coro`` as an ``asyncio.Task`` under the current OTel context.

    ``asyncio.create_task`` copies the ambient ``contextvars.Context`` at
    creation time, so the OTel "current span" usually does propagate into the
    task on its own. We do it explicitly anyway: the captured context is the one
    live at the *scheduling* call site, so any span started inside the coroutine
    is parented to that span rather than to whatever happens to be current when
    the event loop later resumes the task. This keeps background recommendation
    work and fire-and-forget logging tasks attached to their request's trace
    instead of starting orphan roots.

    Args:
        coro: The coroutine to run in the background.
        name: Optional ``asyncio.Task`` name, useful when inspecting pending
            tasks during debugging.

    Returns:
        The scheduled ``asyncio.Task``. Its result/exception behavior is
        identical to ``asyncio.create_task(coro)``.
    """
    captured = otel_context.get_current()

    async def _runner() -> _T:
        token = otel_context.attach(captured)
        try:
            return await coro
        finally:
            otel_context.detach(token)

    return asyncio.create_task(_runner(), name=name)