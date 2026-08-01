"""Offline evaluation harness for the Reelix recommendation agent.

Read-only access to the logging tables (`store`), an LLM-as-judge built on the
Anthropic SDK (`judge`), a stage-scoped replay engine for verifying prompt
changes (`replay`), and a markdown report writer (`report`).

Nothing here is imported by the serving path — the API and MCP server never
depend on this package.
"""

__all__ = ["db", "judge", "replay", "report", "store"]