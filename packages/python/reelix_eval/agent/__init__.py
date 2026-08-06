"""The Investigator — a Claude Agent SDK agent that reads the logs and proposes fixes.

Named for what it does rather than the package that houses it: `reelix_eval` is
the eval toolkit (judge, replay, metrics queries), and this agent is one consumer
of it alongside the `eval_judge` and `eval_metrics` jobs. Its own work runs wider
than eval — it triages, locates the responsible code, and proposes diffs.

Layers:

- `tools`     in-process MCP tools wrapping the Phase 1 library
- `subagents` three context-isolated specialists (metrics, queries, verification)
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