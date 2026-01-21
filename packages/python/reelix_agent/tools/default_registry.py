"""
Default tool registry factory.

Call build_registry() at app startup to get a registry with all available tools.
"""

from reelix_agent.tools.registry import ToolRegistry
from reelix_agent.tools.recommendation_tool import recommendation_agent_spec


def build_registry() -> ToolRegistry:
    """Build the default tool registry with all available tools.

    Call this once at app startup and inject into orchestrator functions.

    Returns:
        ToolRegistry with all registered tools.
    """
    registry = ToolRegistry()

    # Register recommendation_agent (terminal tool)
    registry.register(recommendation_agent_spec)

    # Future tools can be registered here:
    # registry.register(search_tool_spec)
    # registry.register(filter_tool_spec)

    return registry
