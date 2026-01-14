from __future__ import annotations
import json
from typing import Any

from pydantic import ValidationError

from .registry import ToolRegistry
from .types import ToolContext, ToolResult

class ToolRunner:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def run(self, *, decision: Any, ctx: ToolContext) -> ToolResult:
        """
        decision: LlmDecision-like (tool_name, tool_args, tool_call_id)
        Mutates ctx.state in a consistent way + appends the standardized tool message.
        """
        tool_name = decision.tool_name
        spec = self.registry.get(tool_name)
        if spec is None:
            payload = {"error": f"Unknown tool '{tool_name}'", "args": decision.tool_args or {}}
            self._append_tool_message(ctx.state, decision, tool_name, payload)
            return ToolResult(payload=payload, terminal=True)

        # 1) Validate args
        try:
            args_obj = spec.args_model.model_validate(decision.tool_args or {})
        except ValidationError as e:
            payload = {"error": "Tool args validation failed", "tool": tool_name, "detail": e.errors()}
            self._append_tool_message(ctx.state, decision, tool_name, payload)
            return ToolResult(payload=payload, terminal=True)

        # 2) Execute
        try:
            result = await spec.handler(ctx, args_obj)
        except Exception as e:
            payload = {"error": "Tool execution failed", "tool": tool_name, "detail": str(e)}
            self._append_tool_message(ctx.state, decision, tool_name, payload)
            return ToolResult(payload=payload, terminal=True)

        # 3) Apply state patch
        for k, v in (result.state_patch or {}).items():
            setattr(ctx.state, k, v)

        # 4) Append tool result message (ALWAYS name == invoked tool)
        self._append_tool_message(ctx.state, decision, tool_name, result.payload or {})
        return result

    def _append_tool_message(self, state: Any, decision: Any, tool_name: str, payload: dict[str, Any]) -> None:
        state.messages.append(
            {
                "role": "tool",
                "name": tool_name,
                "tool_call_id": decision.tool_call_id,
                "content": json.dumps(payload, ensure_ascii=False),
            }
        )
