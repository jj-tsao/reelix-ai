"""The eval agent — a Claude Agent SDK agent that reads the logs and proposes fixes.

Layers:

- `tools`     in-process MCP tools wrapping the Phase 1 library
- `subagents` three context-isolated specialists (metrics, traces, verification)
- `prompts`   the workflow and, more importantly, the evidence standards
- `run`       options assembly, the safety gate, and the run loop

Read-only by default. Under `--apply` the agent may branch and edit, but
`git push` is denied unconditionally in every mode.
"""

from reelix_eval.agent.run import RunConfig, build_options, check_bash, preflight, run
from reelix_eval.agent.tools import ToolContext, build_server, configure

__all__ = [
    "RunConfig",
    "ToolContext",
    "build_options",
    "build_server",
    "check_bash",
    "configure",
    "preflight",
    "run",
]