from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Generic, TypeVar

from pydantic import BaseModel, ValidationError

TArgs = TypeVar("TArgs", bound=BaseModel)

@dataclass(frozen=True)
class ToolSpec(Generic[TArgs]):
    name: str
    description: str
    args_model: type[TArgs]
    handler: Callable[..., Awaitable[dict[str, Any]]]
    version: str = "v1"
    terminal: bool = True
    tags: tuple[str, ...] = ()

    def openai_tool(self) -> dict[str, Any]:
        # single source of truth for the tool schema
        schema = self.args_model.model_json_schema()
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": schema,
            },
        }

@dataclass
class ToolRunResult:
    tool_name: str
    ok: bool
    output: dict[str, Any]
    trace: dict[str, Any]
    tool_message: dict[str, Any] | None = None


class ToolRegistry:
    def __init__(self, specs: list[ToolSpec[Any]]) -> None:
        self._specs = {s.name: s for s in specs}

    def get(self, name: str) -> ToolSpec[Any] | None:
        return self._specs.get(name)

    def openai_tools(self) -> list[dict[str, Any]]:
        return [s.openai_tool() for s in self._specs.values()]


class ToolRunner:
    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    async def run(
        self,
        *,
        state,                  # AgentState
        tool_name: str,
        tool_args: dict[str, Any],
        tool_call_id: str | None,
        deps: dict[str, Any],   # inject agent_rec_runner, llm_client, etc.
    ) -> ToolRunResult:
        spec = self._registry.get(tool_name)
        if not spec:
            out = {"error": "unknown_tool", "tool": tool_name}
            return ToolRunResult(
                tool_name=tool_name,
                ok=False,
                output=out,
                trace={"tool": tool_name, "ok": False, "error": "unknown_tool"},
                tool_message=_tool_msg(tool_name, tool_call_id, out),
            )

        t0 = time.perf_counter()
        try:
            args_obj = spec.args_model.model_validate(tool_args)
        except ValidationError as e:
            out = {"error": "validation_error", "detail": e.errors()}
            return ToolRunResult(
                tool_name=tool_name,
                ok=False,
                output=out,
                trace={"tool": tool_name, "ok": False, "error": "validation_error"},
                tool_message=_tool_msg(tool_name, tool_call_id, out),
            )

        try:
            out = await spec.handler(state=state, args=args_obj, **deps)
            ok = True
            err = None
        except Exception as e:
            out = {"error": "tool_exception", "message": str(e)}
            ok = False
            err = "tool_exception"

        dt_ms = (time.perf_counter() - t0) * 1000
        trace = {
            "tool": tool_name,
            "version": spec.version,
            "ok": ok,
            "error": err,
            "latency_ms": round(dt_ms, 1),
        }

        # If you ever loop LLM after tool execution, include tool_message.
        tool_message = _tool_msg(tool_name, tool_call_id, out)
        return ToolRunResult(tool_name=tool_name, ok=ok, output=out, trace=trace, tool_message=tool_message)


def _tool_msg(tool_name: str, tool_call_id: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "tool",
        "name": tool_name,
        "tool_call_id": tool_call_id,
        "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    }
