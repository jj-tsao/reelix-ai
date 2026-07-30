"""Transport-agnostic runtime for the Reelix recommendation stack.

Provides the bootstrap factories, Redis stores, and telemetry helpers shared
by every transport (FastAPI app, MCP server). Apps construct their runtime
here and layer transport-specific wiring (routes, tools, instrumentation)
on top.
"""

from reelix_runtime.factory import (
    RecommendationRuntime,
    Stores,
    build_recommendation_runtime,
    build_stores,
    build_telemetry,
)
from reelix_runtime.settings import RuntimeSettings

__all__ = [
    "RecommendationRuntime",
    "RuntimeSettings",
    "Stores",
    "build_recommendation_runtime",
    "build_stores",
    "build_telemetry",
]
