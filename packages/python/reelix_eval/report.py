"""Run-report writer — markdown for humans, JSON for machines.

Writes `<root>/<run_id>/report.md` and `<root>/<run_id>/findings.json`. Report
directories are gitignored so run artifacts never pollute a fix branch's diff.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

Confidence = Literal["high", "medium", "low"]

#: Gaps the harness knows about, so a run never mistakes missing data for a
#: healthy signal. Extended per-run with whatever the agent couldn't reach.
STANDING_BLIND_SPOTS = [
    "The explanation agent emits no telemetry rows — explanations stream from a "
    "separate `/explore/why` request that writes only an OTel span. Explanation "
    "quality is observable only through the judge, and its token cost is not "
    "counted anywhere.",
    "`request_traces` has a series break on 2026-08-01: tool-level failures that "
    "had been logged as `completed` began counting as errors, and curator tokens "
    "began being summed. Window comparisons spanning that date show phantom "
    "regressions in `error_rate`, `llm_calls`, and token totals.",
    "Only the curator stage is replayable. Retrieval-level findings (weights, "
    "recipes, cross-encoder) are reported as unverified proposals.",
    "`curator_evaluations.structure_fit` is always 0 — the curator prompt scores "
    "three dimensions, but the tiering code sums four. `total_fit` therefore "
    "ranges 0-6, not the 0-8 its docstring claims.",
]


@dataclass
class Finding:
    """One ranked problem, with the evidence that supports it."""

    title: str
    symptom: str
    evidence: str
    hypothesis: str
    confidence: Confidence
    proposed_fix: str
    location: str | None = None
    query_ids: list[str] = field(default_factory=list)
    verified: bool | None = None
    verification_note: str | None = None


@dataclass
class HealthRow:
    metric: str
    group: str
    baseline: float | None
    current: float | None
    verdict: str
    baseline_n: int = 0
    current_n: int = 0


def git_sha(repo_root: Path | str) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _fmt(v: float | None, places: int = 3) -> str:
    if v is None:
        return "—"
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    return f"{round(v, places):g}"


def _delta_cell(baseline: float | None, current: float | None) -> str:
    if baseline is None or current is None:
        return "—"
    diff = current - baseline
    if baseline == 0:
        return f"{diff:+.3g}"
    return f"{diff:+.3g} ({diff / abs(baseline):+.1%})"


@dataclass
class Report:
    run_id: str
    window: str
    baseline_window: str | None = None
    judge_model: str | None = None
    system_models: str = "gpt-4.1-mini (orchestrator, curator), gpt-4o-mini (chat)"
    sample_sizes: dict[str, int] = field(default_factory=dict)
    health: list[HealthRow] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    applied_branch: str | None = None
    applied_files: list[str] = field(default_factory=list)
    verification: dict[str, Any] | None = None
    extra_blind_spots: list[str] = field(default_factory=list)
    git_sha: str = "unknown"

    def to_markdown(self) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        out: list[str] = [
            f"# Reelix eval run `{self.run_id}`",
            "",
            f"- **Generated**: {ts}",
            f"- **Window**: {self.window}",
        ]
        if self.baseline_window:
            out.append(f"- **Baseline window**: {self.baseline_window}")
        out += [
            f"- **Git SHA**: `{self.git_sha}`",
            f"- **System under test**: {self.system_models}",
        ]
        if self.judge_model:
            out.append(f"- **Judge**: {self.judge_model}")
        if self.sample_sizes:
            sizes = ", ".join(f"{k}={v}" for k, v in sorted(self.sample_sizes.items()))
            out.append(f"- **Sample sizes**: {sizes}")
        out.append("")

        # -- Health ------------------------------------------------------
        out += ["## Health", ""]
        if self.health:
            out += [
                "| Metric | Group | Baseline | Current | Delta | n (base/curr) | Verdict |",
                "|---|---|---:|---:|---:|:---:|---|",
            ]
            for r in self.health:
                out.append(
                    f"| `{r.metric}` | {r.group} | {_fmt(r.baseline)} | "
                    f"{_fmt(r.current)} | {_delta_cell(r.baseline, r.current)} | "
                    f"{r.baseline_n}/{r.current_n} | {r.verdict} |"
                )
        else:
            out.append("_No metrics available for this window._")
        out.append("")

        # -- Findings ----------------------------------------------------
        out += ["## Findings", ""]
        if not self.findings:
            out += ["Nothing actionable found in this window.", ""]
        else:
            for i, f in enumerate(self.findings, 1):
                out += [f"### {i}. {f.title}", ""]
                out.append(f"- **Confidence**: {f.confidence}")
                if f.location:
                    out.append(f"- **Location**: `{f.location}`")
                if f.verified is not None:
                    mark = "verified by replay" if f.verified else "NOT confirmed by replay"
                    note = f" — {f.verification_note}" if f.verification_note else ""
                    out.append(f"- **Verification**: {mark}{note}")
                out += [
                    "",
                    f"**Symptom.** {f.symptom}",
                    "",
                    f"**Evidence.** {f.evidence}",
                    "",
                    f"**Hypothesis.** {f.hypothesis}",
                    "",
                    "**Proposed fix.**",
                    "",
                    f.proposed_fix,
                    "",
                ]
                if f.query_ids:
                    shown = ", ".join(f"`{q}`" for q in f.query_ids[:10])
                    more = f" (+{len(f.query_ids) - 10} more)" if len(f.query_ids) > 10 else ""
                    out += [f"**Query IDs.** {shown}{more}", ""]

        # -- Applied changes ---------------------------------------------
        if self.applied_branch:
            out += ["## Applied changes", "", f"Branch: `{self.applied_branch}`", ""]
            if self.applied_files:
                out += ["Files touched:", ""]
                out += [f"- `{p}`" for p in self.applied_files]
                out.append("")

        # -- Verification -------------------------------------------------
        out += ["## Verification (A/B)", ""]
        if not self.verification:
            out += [
                "_No replay was run. Findings above are proposals, not verified fixes._",
                "",
            ]
        else:
            v = self.verification
            out += [
                f"Eval set: `{v.get('evalset', '?')}` "
                f"({v.get('cases', '?')} cases, {v.get('cases_failed', 0)} failed)",
                "",
                "| Measure | Baseline | Replay | Delta |",
                "|---|---:|---:|---:|",
            ]
            for row in v.get("rows", []):
                out.append(
                    f"| {row['name']} | {_fmt(row.get('baseline'))} | "
                    f"{_fmt(row.get('current'))} | "
                    f"{_delta_cell(row.get('baseline'), row.get('current'))} |"
                )
            out.append("")
            if v.get("note"):
                out += [v["note"], ""]

        # -- Blind spots ---------------------------------------------------
        out += ["## Known blind spots", ""]
        for b in STANDING_BLIND_SPOTS + self.extra_blind_spots:
            out.append(f"- {b}")
        out.append("")

        return "\n".join(out)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "window": self.window,
            "baseline_window": self.baseline_window,
            "git_sha": self.git_sha,
            "judge_model": self.judge_model,
            "sample_sizes": self.sample_sizes,
            "health": [asdict(r) for r in self.health],
            "findings": [asdict(f) for f in self.findings],
            "applied_branch": self.applied_branch,
            "applied_files": self.applied_files,
            "verification": self.verification,
            "blind_spots": STANDING_BLIND_SPOTS + self.extra_blind_spots,
        }


def write(report: Report, root: Path | str) -> Path:
    """Write `report.md` + `findings.json` under `<root>/<run_id>/`."""
    out_dir = Path(root) / report.run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    md_path = out_dir / "report.md"
    md_path.write_text(report.to_markdown(), encoding="utf-8")

    json_path = out_dir / "findings.json"
    json_path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )

    logger.info("Wrote report → %s", md_path)
    return md_path