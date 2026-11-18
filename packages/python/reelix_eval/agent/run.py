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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, PermissionResultAllow, PermissionResultDeny

from reelix_eval.agent import tools as tools_mod
from reelix_eval.agent.tools import REPO_ROOT, ToolContext

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_MAX_TURNS = 60

WRITE_TOOLS = ["Edit", "Write", "Bash"]

@dataclass
class RunConfig:
    since: str = "7d"
    query_ids: tuple[str, ...] = ()
    stage_timeout_seconds: float = 300.
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
    """Legacy entry point retained solely to deny shell execution in all modes."""
    return _deny("Bash and remediation execution are disabled in host-owned M2.")


def build_guard(apply_mode: bool):
    """The `can_use_tool` callback."""

    async def guard(tool_name: str, tool_input: dict[str, Any], context) -> Any:
        if tool_name in WRITE_TOOLS:
            return _deny("Edits and shell execution are disabled in host-owned M2.")
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

    if cfg.apply_mode:
        problems.append("--apply is disabled: M2 permits proposals, never patch execution.")

    return problems


def build_options(cfg: RunConfig, *, executor, request) -> ClaudeAgentOptions:
    """Options require a scoped case executor; there is no unbounded agent path."""
    return executor.build_options(request)


def build_task(cfg: RunConfig) -> str:
    parts = [
        f"Investigate the last {cfg.since} of Reelix traffic.",
    ]
    if cfg.baseline:
        parts.append(f"Compare it against a baseline window of {cfg.baseline}.")
    if cfg.focus:
        parts.append(f"Scope the investigation to the {cfg.focus} stage.")
    parts.append(f"Sample about {cfg.sample_size} queries where you need examples.")
    parts.append("The host owns assurance, one bounded evidence revision, proposal review and publication.")
    parts.append("This run is read-only. Structured stage submissions never grant execution rights.")
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
    """Run host-enforced assurance. llm_client remains accepted for call compatibility."""
    from reelix_eval import store
    from reelix_eval.case import CaseIdentity, InvestigationCase
    from reelix_eval.orchestration import HostOrchestrator
    from reelix_eval.trust import Policy, TrustedContext
    from reelix_eval.agent.stages import ClaudeStageExecutor
    from reelix_eval.replay.isolated import source_manifest, manifest_digest

    problems = preflight(cfg)
    if cfg.apply_mode or (problems and not cfg.dry_run):
        raise RuntimeError("Preflight failed:\n- " + "\n- ".join(problems))
    if cfg.dry_run:
        return {"dry_run": True, "run_id": cfg.run_id, "task": build_task(cfg),
                "model": cfg.model, "apply_mode": False, "max_turns": cfg.max_turns,
                "stage_timeout_seconds": cfg.stage_timeout_seconds, "max_revision_cycles": 1,
                "evalsets_dir": str(cfg.resolved_evalsets_dir()),
                "reports_dir": str(cfg.resolved_reports_dir()),
                "allowed_tools": ["scoped telemetry", "scoped source", "finding binding", "specialist delegation"],
                "subagents": ["metrics-analyst", "query-inspector"], "preflight_problems": problems}
    reports = cfg.resolved_reports_dir()
    # Validate the path before any external I/O. Refuse to reuse historical output.
    from reelix_eval.report import Report, git_sha
    Report(cfg.run_id, cfg.since).validate()
    if (reports / cfg.run_id).exists():
        return {"run_id": cfg.run_id, "report": None, "is_error": True,
                "status": "failed", "reason": "report already exists; use a new run ID"}
    if engine is None:
        from reelix_eval.db import get_engine
        engine = get_engine()
    current = store.parse_since(cfg.since)
    baseline = store.parse_since(cfg.baseline) if cfg.baseline else (current[0] - (current[1] - current[0]), current[0])
    windows = (baseline, current)
    # Scope discovery is a read-only authorization step, not diagnostic selection.
    permitted = tuple(sorted({q for lo, hi in windows for q in store.incident_query_ids(engine, lo, hi)}))
    if cfg.query_ids:
        if not set(cfg.query_ids) <= set(permitted):
            raise RuntimeError("Requested query IDs are outside the incident window.")
        permitted = cfg.query_ids
    policy = Policy()
    revision = manifest_digest(source_manifest(REPO_ROOT / 'packages/python'))
    ctx = TrustedContext(case_id=cfg.run_id, query_ids=permitted, current_revision=revision)
    identity = CaseIdentity(cfg.run_id, build_task(cfg), str(current), permitted, revision, policy.revision, source_commit=git_sha(REPO_ROOT))
    case = InvestigationCase(identity, reports / '.cases')
    tools_mod.configure(ToolContext(engine=engine, evalsets_dir=cfg.resolved_evalsets_dir(),
        reports_dir=reports, run_id=cfg.run_id, apply_mode=False))
    executor = ClaudeStageExecutor(cfg, case, ctx, windows=windows)
    result = await HostOrchestrator(case, ctx, executor, reports, policy=policy,
        max_turns=cfg.max_turns, timeout_seconds=cfg.stage_timeout_seconds).run()
    result.update(turns=executor.turns, cost_usd=executor.cost_usd)
    return result
