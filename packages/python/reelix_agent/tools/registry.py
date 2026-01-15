from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

from .types import ToolSpec

@dataclass
class ToolRegistry:
    _tools: dict[str, ToolSpec[Any]] = field(default_factory=dict)

    def register(self, spec: ToolSpec[Any]) -> None:
        if spec.name in self._tools:
            raise ValueError(f"Tool already registered: {spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec[Any] | None:
        return self._tools.get(name)

    def openai_tools(self) -> list[dict[str, Any]]:
        return [t.openai_tool_schema() for t in self._tools.values()]

    # MCP-shaped: this is basically your future `list_tools`
    def catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "schema": t.args_model.model_json_schema(),
                "terminal": t.terminal,
            }
            for t in self._tools.values()
        ]
