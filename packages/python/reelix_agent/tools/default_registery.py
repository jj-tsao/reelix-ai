# reelix_agent/tools/default_registry.py
from __future__ import annotations
from .registry import ToolRegistry
from .types import ToolSpec
from .recommendation_tool import recommendation_handler, RecommendationArgs

def build_registry() -> ToolRegistry:
    r = ToolRegistry()
    r.register(
        ToolSpec(
            name="recommendation_agent",
            description="Retrieve, rank, and produce a final recommendation slate.",
            args_model=RecommendationArgs,
            handler=recommendation_handler,
            terminal=True,
        )
    )
    return r
