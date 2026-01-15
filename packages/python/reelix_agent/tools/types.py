from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, TypeVar, Generic

from pydantic import BaseModel

# from reelix_agent.orchestrator.agent_state import AgentState

Json = dict[str, Any]

@dataclass(frozen=True)
class ToolContext:
    state: Any                  # AgentState
    agent_rec_runner: Any       # AgentRecRunner
    llm_client: Any             # LlmClient

class ToolResult(BaseModel):
    payload: Json = {}
    state_patch: Json = {}      # patch AgentState fields deterministically
    terminal: bool = True       # whether orchestrator should stop after this tool

TArgs = TypeVar("TArgs", bound=BaseModel)
ToolHandler = Callable[[ToolContext, TArgs], Awaitable[ToolResult]]

@dataclass(frozen=True)
class ToolSpec(Generic[TArgs]):
    name: str
    description: str
    args_model: type[TArgs]
    handler: ToolHandler[TArgs]
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
