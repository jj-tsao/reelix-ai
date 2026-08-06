"""Agent assembly, safety gate, and the run loop.

The agent's own turns run inside the SDK's `claude` subprocess under the Claude
Code login. The judge runs in *this* process against the Messages API with its
own key. Keeping those apart is why `REELIX_JUDGE_ANTHROPIC_KEY` is never
exported as `ANTHROPIC_API_KEY`: that name is resolved first by both the SDK and
the CLI, so exporting it would silently move every agent turn onto
pay-as-you-go.
"""

from __future__ import annotations

import logging
import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

from reelix_eval.agent import tools as tools_mod
from reelix_eval.agent.prompts import build_prompt
from reelix_eval.agent.subagents import build_agents
from reelix_eval.agent.tools import REPO_ROOT, TOOL_NAMES, ToolContext, build_server
from reelix_eval.judge import JudgeConfig

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_MAX_TURNS = 60

#: Read-only capability set. The agent can look at anything and call every eval
#: tool, but cannot change the working tree or run a command.
READ_ONLY_TOOLS = ["Read", "Grep", "Glob", "Task", *TOOL_NAMES]
WRITE_TOOLS = ["Edit", "Write", "Bash"]

#: Git subcommands permitted under --apply. Deliberately excludes anything that
#: reaches the network or rewrites history.
_GIT_ALLOWED = {
    "status",
    "diff",
    "log",
    "rev-parse",
    "branch",
    "checkout",
    "add",
    "commit",
    "show",
    "stash",
}

#: Never allowed, in any mode. This repo has a live remote and the eval layer
#: lands on main; an agent with commit rights and a reachable push is the one
#: genuinely dangerous combination here.
_GIT_FORBIDDEN = {"push", "remote", "fetch", "pull", "clone", "submodule"}

#: Operators that would let an allowed prefix carry a forbidden payload.
_CHAIN_RE = re.compile(r"(\|\||&&|;|\||\n|`|\$\()")


@dataclass
class RunConfig:
    since: str = "7d"
    baseline: str | None = None
    focus: str | None = None
    evalset: str = "default"
    sample_size: int = 20
    judge_model: str | None = None
    model: str = DEFAULT_MODEL
    max_turns: int = DEFAULT_MAX_TURNS
    apply_mode: bool = False
    dry_run: bool = False
    #: Where snapshots and reports land. Left unset they resolve against the
    #: current working directory, which suits an ad-hoc run from a shell; the
    #: `investigate` job passes explicit paths anchored to its own app directory
    #: so output does not follow whoever happened to invoke it.
    evalsets_dir: Path | None = None
    reports_dir: Path | None = None
    run_id: str = field(
        default_factory=lambda: "eval-"
        + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    )

    def resolved_evalsets_dir(self) -> Path:
        return self.evalsets_dir or Path.cwd() / "evalsets"

    def resolved_reports_dir(self) -> Path:
        return self.reports_dir or Path.cwd() / "reports"


# ---------------------------------------------------------------------------
# Safety gate
# ---------------------------------------------------------------------------

def _deny(msg: str) -> PermissionResultDeny:
    logger.warning("DENIED: %s", msg)
    return PermissionResultDeny(message=msg)


def check_bash(command: str, apply_mode: bool) -> PermissionResultAllow | PermissionResultDeny:
    """Validate one Bash invocation against the allowlist.

    Split out from the callback so it can be unit-tested without an agent.
    """
    if not apply_mode:
        return _deny("Bash is disabled in read-only mode. Re-run with --apply.")

    if _CHAIN_RE.search(command):
        return _deny(
            "Chained or substituted shell commands are not allowed — an allowed "
            "prefix could carry a forbidden payload. Issue one command at a time."
        )

    try:
        parts = shlex.split(command)
    except ValueError as e:
        return _deny(f"Could not parse command: {e}")

    if not parts:
        return _deny("Empty command.")

    if parts[0] != "git":
        return _deny(f"Only git commands are allowed; got {parts[0]!r}.")

    subcommands = [p for p in parts[1:] if not p.startswith("-")]
    if not subcommands:
        return _deny("git requires a subcommand.")
    sub = subcommands[0]

    # Checked before the allowlist so a forbidden verb can never slip through as
    # an argument to an allowed one.
    if any(p in _GIT_FORBIDDEN for p in parts[1:]):
        return _deny(
            "Pushing and other remote git operations are denied unconditionally, "
            "in every mode. Publishing is a human action."
        )

    if sub not in _GIT_ALLOWED:
        return _deny(
            f"git {sub} is not in the allowlist "
            f"({', '.join(sorted(_GIT_ALLOWED))})."
        )

    # `git checkout -b <new>` is fine; `git checkout <path>` discards work.
    if sub == "checkout" and "-b" not in parts:
        return _deny("Only `git checkout -b <branch>` is allowed, to avoid discarding changes.")

    return PermissionResultAllow()


def build_guard(apply_mode: bool):
    """The `can_use_tool` callback."""

    async def guard(tool_name: str, tool_input: dict[str, Any], context) -> Any:
        if tool_name == "Bash":
            return check_bash(str(tool_input.get("command", "")), apply_mode)

        if tool_name in ("Edit", "Write") and not apply_mode:
            return _deny("File edits are disabled in read-only mode. Re-run with --apply.")

        if tool_name in ("Edit", "Write"):
            path = str(tool_input.get("file_path", ""))
            resolved = Path(path).resolve()
            if not str(resolved).startswith(str(REPO_ROOT)):
                return _deny(f"Refusing to edit outside the repo: {path}")

        return PermissionResultAllow()

    return guard


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

def preflight(cfg: RunConfig) -> list[str]:
    """Blocking problems, as human-readable strings. Empty means good to go."""
    problems: list[str] = []

    if os.getenv("ANTHROPIC_API_KEY"):
        problems.append(
            "ANTHROPIC_API_KEY is set. It shadows the Claude Code login, so agent "
            "turns would bill as pay-as-you-go instead of using the plan credit. "
            "Unset it; the judge uses REELIX_JUDGE_ANTHROPIC_KEY."
        )

    if not os.getenv("REELIX_JUDGE_ANTHROPIC_KEY"):
        problems.append("REELIX_JUDGE_ANTHROPIC_KEY is not set — run_judge will fail.")

    if cfg.apply_mode:
        # Untracked files are expected (reports/, evalsets/ and any scratch), so
        # a naive clean-tree check would refuse to run every time.
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if dirty:
            problems.append(
                "Working tree has uncommitted changes; --apply would mix them into "
                f"the fix branch:\n{dirty}"
            )

    return problems


def build_options(cfg: RunConfig) -> ClaudeAgentOptions:
    # Edit/Write/Bash are deliberately NEVER listed in allowed_tools, in either
    # mode. Listing a tool there auto-approves it *before* `can_use_tool` is
    # consulted, so putting them in the allow list under --apply would silently
    # bypass the entire guard — including the unconditional `git push` denial.
    # Omitting them makes every call fall through to the callback, which is the
    # only thing standing between the agent and the remote. The SDK emits
    # CanUseToolShadowedWarning if this is ever regressed.
    #
    # Read-only mode additionally hard-blocks them via disallowed_tools, so the
    # agent cannot invoke them at all rather than being denied per call.
    return ClaudeAgentOptions(
        model=cfg.model,
        system_prompt=build_prompt(focus=cfg.focus, apply_mode=cfg.apply_mode),
        # Ignore ~/.claude and repo settings: this agent's configuration is
        # explicit, so a run can't be silently changed by unrelated local config.
        setting_sources=[],
        cwd=str(REPO_ROOT),
        max_turns=cfg.max_turns,
        mcp_servers={"reelix_eval": build_server()},
        agents=build_agents(),
        allowed_tools=list(READ_ONLY_TOOLS),
        disallowed_tools=[] if cfg.apply_mode else list(WRITE_TOOLS),
        can_use_tool=build_guard(cfg.apply_mode),
        permission_mode="default",
    )


def build_task(cfg: RunConfig) -> str:
    parts = [
        f"Investigate the last {cfg.since} of Reelix traffic.",
    ]
    if cfg.baseline:
        parts.append(f"Compare it against a baseline window of {cfg.baseline}.")
    if cfg.focus:
        parts.append(f"Scope the investigation to the {cfg.focus} stage.")
    parts.append(f"Sample about {cfg.sample_size} queries where you need examples.")
    if cfg.apply_mode:
        parts.append(
            "Edits are enabled: snapshot an eval set from pre-change traffic, "
            "create a branch, make the smallest change that tests your top "
            "hypothesis, then verify it with fix-verifier."
        )
    else:
        parts.append("This run is read-only: propose diffs, do not apply them.")
    parts.append(f"Finish by calling write_report. The run id is {cfg.run_id}.")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

async def _stream_prompt(task: str, session_id: str):
    """Yield the task as a streaming-mode message.

    The SDK requires streaming input whenever `can_use_tool` is set — a plain
    string prompt raises. Since the permission guard is the whole safety story
    here, streaming is mandatory rather than optional.
    """
    yield {
        "type": "user",
        "message": {"role": "user", "content": task},
        "parent_tool_use_id": None,
        "session_id": session_id,
    }


async def run(cfg: RunConfig, engine=None, llm_client=None) -> dict[str, Any]:
    """Execute one investigation. Returns a small summary dict."""
    from reelix_eval.db import get_engine

    problems = preflight(cfg)
    if problems:
        for p in problems:
            logger.error("preflight: %s", p)
        if not cfg.dry_run:
            raise RuntimeError("Preflight failed:\n- " + "\n- ".join(problems))

    judge_cfg = JudgeConfig(
        model=cfg.judge_model or JudgeConfig().model,
    )

    tools_mod.configure(
        ToolContext(
            engine=engine or get_engine(),
            evalsets_dir=cfg.resolved_evalsets_dir(),
            reports_dir=cfg.resolved_reports_dir(),
            llm_client=llm_client or _default_llm_client(),  # The OpenAI client used for curator replay
            judge_cfg=judge_cfg,
            run_id=cfg.run_id,
            apply_mode=cfg.apply_mode,
        )
    )

    task = build_task(cfg)
    options = build_options(cfg)

    if cfg.dry_run:
        return {
            "dry_run": True,
            "run_id": cfg.run_id,
            "task": task,
            "model": cfg.model,
            "judge_model": judge_cfg.model,
            "apply_mode": cfg.apply_mode,
            "evalsets_dir": str(cfg.resolved_evalsets_dir()),
            "reports_dir": str(cfg.resolved_reports_dir()),
            "allowed_tools": options.allowed_tools,
            "subagents": list((options.agents or {}).keys()),
            "max_turns": cfg.max_turns,
            "preflight_problems": problems,
        }

    summary: dict[str, Any] = {"run_id": cfg.run_id, "tool_calls": [], "report": None}

    async for message in query(prompt=_stream_prompt(task, cfg.run_id), options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    logger.info("agent: %s", block.text.strip()[:400])
                elif isinstance(block, ToolUseBlock):
                    summary["tool_calls"].append(block.name)
                    logger.info("tool: %s", block.name)
        elif isinstance(message, ResultMessage):
            summary["turns"] = message.num_turns
            summary["cost_usd"] = message.total_cost_usd
            summary["is_error"] = message.is_error
            summary["result"] = message.result
            if message.result:
                logger.info("result: %s", message.result[:800])

    ctx = tools_mod._require_ctx()
    report_path = ctx.reports_dir / cfg.run_id / "report.md"
    if report_path.exists():
        summary["report"] = str(report_path)

    return summary


def _default_llm_client():
    """The OpenAI client used for curator replay — the system under test."""
    try:
        from reelix_core.llm_client import LlmClient

        return LlmClient(
            model="gpt-4.1-mini", api_key=os.getenv("OPENAI_API_KEY"), timeout=60.0
        )
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("No replay LLM client available: %s", e)
        return None
