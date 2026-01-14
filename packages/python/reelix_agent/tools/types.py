from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Type

from pydantic import BaseModel

Json = dict[str, Any]

@dataclass(frozen=True)
class ToolContext:
    # Keep this small; pass services explicitly
    state: Any                  # AgentState
    agent_rec_runner: Any       # AgentRecRunner
    llm_client: Any             # LlmClient

class ToolResult(BaseModel):
    payload: Json = {}
    state_patch: Json = {}      # patch AgentState fields deterministically
    terminal: bool = True       # whether orchestrator should stop after this tool

@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: Type[BaseModel]
    handler: Callable[[ToolContext, BaseModel], Awaitable[ToolResult]]
    terminal: bool = True

    def openai_tool_schema(self) -> Json:
        schema = self.args_model.model_json_schema()
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": schema,
            },
        }
