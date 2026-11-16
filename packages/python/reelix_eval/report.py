"""Run-report writer — markdown for humans, JSON for machines.

Writes `<root>/<run_id>/report.md` and `<root>/<run_id>/findings.json`. Report
directories are gitignored so run artifacts never pollute a fix branch's diff.
"""

from __future__ import annotations

import json
import logging
import math
import copy
import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from reelix_eval.verification import VerificationReceipt

logger = logging.getLogger(__name__)

Confidence = Literal["high", "medium", "low"]


class ReportValidationError(ValueError):
    """Field locations/reasons only: never include supplied evidence or secrets."""


def parse_json_field(raw: Any, name: str, kind: type, *, optional: bool = False):
    if raw is None:
        if optional:
            return None
        raise ReportValidationError(f"{name}: required")
    if isinstance(raw, str):
        try:
            def invalid_constant(_):
                raise ValueError()
            def unique_fields(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ReportValidationError(f"{name}: duplicate JSON fields")
                    result[key] = value
                return result
            raw = json.loads(raw, parse_constant=invalid_constant, object_pairs_hook=unique_fields)
        except ReportValidationError:
            raise
        except json.JSONDecodeError as exc:
            raise ReportValidationError(f"{name}: invalid JSON at line {exc.lineno}, column {exc.colno}") from None
        except ValueError:
            raise ReportValidationError(f"{name}: non-finite JSON number") from None
    if raw is None and optional:
        return None
    if not isinstance(raw, kind):
        raise ReportValidationError(f"{name}: expected {kind.__name__}")
    return raw


def finding_from_dict(value: Any, path: str = "finding") -> "Finding":
    if not isinstance(value, dict):
        raise ReportValidationError(f"{path}: expected object")
    required = ("title", "symptom", "evidence", "hypothesis", "confidence", "proposed_fix")
    allowed = set(Finding.__dataclass_fields__)
    if set(value) - allowed:
        raise ReportValidationError(f"{path}: unknown fields")
    for name in required:
        if name not in value:
            raise ReportValidationError(f"{path}.{name}: required")
        if not isinstance(value[name], str) or (name != "proposed_fix" and not value[name].strip()):
            raise ReportValidationError(f"{path}.{name}: expected nonempty text")
    if value['confidence'] not in ('high', 'medium', 'low'):
        raise ReportValidationError(f"{path}.confidence: expected high, medium or low")
    for name in ('location', 'verification_note', 'verification_id'):
        if value.get(name) is not None and not isinstance(value[name], str):
            raise ReportValidationError(f"{path}.{name}: expected text or null")
    ids = value.get('query_ids', [])
    if not isinstance(ids, list) or any(not isinstance(q, str) or not q for q in ids):
        raise ReportValidationError(f"{path}.query_ids: expected list of IDs")
    if value.get('verified') is not None and type(value['verified']) is not bool:
        raise ReportValidationError(f"{path}.verified: expected boolean or null")
    return Finding(**value)

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
    verification_id: str | None = None


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
    verification: VerificationReceipt | None = None
    verification_receipts: dict[str, VerificationReceipt] = field(default_factory=dict)
    extra_blind_spots: list[str] = field(default_factory=list)
    git_sha: str = "unknown"

    def validate(self) -> None:
        if (not isinstance(self.run_id, str) or self.run_id in ('', '.', '..')
                or '\x00' in self.run_id or '/' in self.run_id or '\\' in self.run_id):
            raise ReportValidationError('run_id: expected a single directory name')
        if not isinstance(self.window, str) or not self.window.strip():
            raise ReportValidationError('window: required text')
        if not isinstance(self.findings, list):
            raise ReportValidationError('findings: expected list')
        if self.verification is not None and not isinstance(self.verification, VerificationReceipt):
            raise ReportValidationError('verification: a host execution receipt is required')
        if not isinstance(self.verification_receipts, dict):
            raise ReportValidationError('verification_receipts: expected host receipt mapping')
        for key, receipt in self.verification_receipts.items():
            if not isinstance(receipt, VerificationReceipt) or key != receipt.receipt_id:
                raise ReportValidationError('verification_receipts: invalid receipt identity')
        if self.verification is not None and self.verification_receipts.get(self.verification.receipt_id) != self.verification:
            raise ReportValidationError('verification: receipt is not registered')
        for i, f in enumerate(self.findings):
            if not isinstance(f, Finding):
                raise ReportValidationError(f'findings[{i}]: expected Finding')
            finding_from_dict(asdict(f), f'findings[{i}]')
            receipt = self.verification_receipts.get(f.verification_id)
            if f.verification_id is not None and receipt is None:
                raise ReportValidationError(f'findings[{i}].verification_id: unknown execution receipt')
            expected = receipt.verified if receipt else None
            if f.verified is not expected:
                raise ReportValidationError(f'findings[{i}].verified: inconsistent with execution receipt (null means not attempted)')
            if receipt and (not f.query_ids or not set(f.query_ids) <= set(receipt.case_ids)):
                raise ReportValidationError(f'findings[{i}].query_ids: not covered by receipt')
        if not isinstance(self.sample_sizes, dict) or any(not isinstance(k,str) for k in self.sample_sizes) or any(type(n) is not int or n < 0 for n in self.sample_sizes.values()):
            raise ReportValidationError('sample_sizes: expected nonnegative integer counts')
        if not isinstance(self.extra_blind_spots, list) or any(not isinstance(s, str) for s in self.extra_blind_spots):
            raise ReportValidationError('blind_spots: expected list of text')
        if not isinstance(self.health, list):
            raise ReportValidationError('health: expected list')
        for h in self.health:
            if not isinstance(h, HealthRow) or any(not isinstance(getattr(h,k), str) for k in ('metric','group','verdict')):
                raise ReportValidationError('health: invalid row')
            if any(type(n) is not int or n < 0 for n in (h.baseline_n,h.current_n)):
                raise ReportValidationError('health: invalid counts')
            if any(v is not None and (type(v) not in (int,float) or not math.isfinite(v)) for v in (h.baseline,h.current)):
                raise ReportValidationError('health: invalid metric value')

    def to_markdown(self) -> str:
        self.validate()
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
                mark = ('not attempted' if f.verified is None else
                        'successful: acceptance criteria satisfied' if f.verified else
                        'attempted: acceptance criteria NOT satisfied')
                out.append(f"- **Verification**: {mark}")
                if f.verification_id:
                    out.append(f"- **Execution receipt**: `{f.verification_id}`")
                out.append("")
                # Skip empty sections rather than emitting a bare heading — an
                # author who put everything in `evidence` should produce a
                # shorter report, not one littered with empty headings.
                for label, text in (
                    ("Symptom", f.symptom),
                    ("Evidence", f.evidence),
                    ("Hypothesis", f.hypothesis),
                ):
                    if (text or "").strip():
                        out += [f"**{label}.** {text.strip()}", ""]
                if (f.proposed_fix or "").strip():
                    out += ["**Proposed fix.**", "", f.proposed_fix.strip(), ""]
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
        if not self.verification_receipts:
            out += [
                "_No verification execution evidence is attached. Findings above are proposals, not verified fixes._",
                "",
            ]
        else:
            for key, v in self.verification_receipts.items():
                out += [f"Receipt `{key}`: **{v.decision}**, verified={json.dumps(v.verified)}", '',
                        f"Cases requested: {len(v.case_ids)}; replay failures: {len(v.failed_case_ids)}; "
                        f"evaluated: {len(v.evaluated_case_ids)}; evaluation failures: {len(v.evaluation_failed_case_ids)}. "
                        f"Revision matched: {v.revision_matched}; outputs valid: {v.outputs_valid}; evaluation valid: {v.evaluation_valid}.", '',
                        '```json', json.dumps(v.to_dict(), indent=2), '```', '']

        # -- Blind spots ---------------------------------------------------
        out += ["## Known blind spots", ""]
        for b in STANDING_BLIND_SPOTS + self.extra_blind_spots:
            out.append(f"- {b}")
        out.append("")

        return "\n".join(out)

    def to_dict(self) -> dict:
        self.validate()
        return {
            "schema_version": 2,
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
            "verification": self.verification.to_dict() if self.verification else None,
            "verification_receipts": {k:v.to_dict() for k,v in self.verification_receipts.items()},
            "blind_spots": STANDING_BLIND_SPOTS + self.extra_blind_spots,
        }


def write(report: Report, root: Path | str) -> Path:
    """Validate/render first, then atomically publish an immutable artifact pair."""
    report = copy.deepcopy(report)
    markdown = report.to_markdown()
    payload = json.dumps(report.to_dict(), indent=2, ensure_ascii=False, allow_nan=False)
    root = Path(root)
    out_dir = Path(root) / report.run_id
    if out_dir.exists():
        raise ReportValidationError('run_id: report already published; use a new run ID')
    root.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix='.report-', dir=root))
    try:
        (staged/'report.md').write_text(markdown, encoding='utf-8')
        (staged/'findings.json').write_text(payload, encoding='utf-8')
        os.rename(staged, out_dir)
    finally:
        if staged.exists():
            shutil.rmtree(staged)
    md_path = out_dir/'report.md'
    logger.info("Wrote report → %s", md_path)
    return md_path
