"""Process-wide application context for the MCP server."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from dataclasses import dataclass, field
from typing import Any

import httpx

from reelix_core.llm_client import LlmClient
from reelix_logging.rec_logger import TelemetryLogger
from reelix_runtime import (
    RecommendationRuntime,
    Stores,
    build_recommendation_runtime,
    build_stores,
    build_telemetry,
)
from reelix_runtime.telemetry.context import traced_create_task

from reelix_mcp.settings import McpSettings

log = logging.getLogger(__name__)


@dataclass
class AppContext:
    """Singletons shared by all tool calls; built once at process start."""

    settings: McpSettings
    runtime: RecommendationRuntime
    stores: Stores
    http_client: httpx.AsyncClient
    logger: TelemetryLogger
    llm: LlmClient
    pending_tasks: set[asyncio.Task] = field(default_factory=set)

    @classmethod
    def build(cls, settings: McpSettings) -> "AppContext":
        log.info("Bootstrapping Reelix recommendation stack…")
        runtime = build_recommendation_runtime(settings)
        stores = build_stores(settings)
        http_client, logger = build_telemetry(settings, timeout_s=5.0)
        return cls(
            settings=settings,
            runtime=runtime,
            stores=stores,
            http_client=http_client,
            logger=logger,
            llm=LlmClient(),
        )

    def spawn(self, coro: Coroutine[Any, Any, Any], *, name: str) -> asyncio.Task:
        """Fire-and-forget a telemetry coroutine under the current OTel context.

        Tasks are strongly referenced until done so they aren't garbage
        collected mid-flight, and ``aclose`` can drain them at shutdown.
        """
        task = traced_create_task(coro, name=name)
        self.pending_tasks.add(task)
        task.add_done_callback(self.pending_tasks.discard)
        return task

    async def aclose(self) -> None:
        """Drain pending telemetry (bounded) and release clients."""
        pending = [t for t in self.pending_tasks if not t.done()]
        if pending:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*pending, return_exceptions=True), timeout=3.0
                )
            except asyncio.TimeoutError:
                log.warning("Dropped %d unfinished telemetry tasks", len(pending))
        await self.http_client.aclose()
        await self.stores.why_cache.aclose()
