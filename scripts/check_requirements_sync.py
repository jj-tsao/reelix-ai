#!/usr/bin/env python3
"""Guard against apps/api dependency drift between pyproject.toml and requirements.txt.

The production Docker image installs from ``apps/api/requirements.txt``, while local
dev resolves ``apps/api/pyproject.toml`` via ``uv``. The two are maintained by hand,
so a dependency added to one can be silently missing from the other — exactly what
broke the Hugging Face Space deploy when OpenTelemetry landed in pyproject.toml only.

This check fails if any *direct* dependency declared in pyproject.toml's
``[project].dependencies`` is absent (by PEP 503 normalized name) from
requirements.txt. Local workspace packages declared as uv path sources (e.g.
``reelix-core``, installed via ``-e ../../packages/python``) are excluded.

Scope note: this is a name-coverage check, not a version check, and it does not
build the Docker image — it only prevents the "declared in pyproject, missing from
the prod manifest" class of drift. Stdlib only (tomllib), so it runs without deps.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "apps" / "api" / "pyproject.toml"
REQUIREMENTS = ROOT / "apps" / "api" / "requirements.txt"

_NAME_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")


def _canonical(name: str) -> str:
    """PEP 503 name normalization (lowercase, runs of -_. collapse to a single -)."""
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def _req_name(spec: str) -> str | None:
    """Canonical package name from a PEP 508 requirement string, or None."""
    m = _NAME_RE.match(spec.strip())
    return _canonical(m.group(1)) if m else None


def pyproject_direct_deps() -> set[str]:
    data = tomllib.loads(PYPROJECT.read_text())
    deps = data.get("project", {}).get("dependencies", [])
    # Exclude local path sources — those ship via the editable `-e` line.
    sources = data.get("tool", {}).get("uv", {}).get("sources", {})
    local = {
        _canonical(k)
        for k, v in sources.items()
        if isinstance(v, dict) and "path" in v
    }
    return {n for d in deps if (n := _req_name(d)) and n not in local}


def requirements_names() -> set[str]:
    names: set[str] = set()
    for raw in REQUIREMENTS.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "-")):  # comments, options, -e/-r
            continue
        line = line.split("#", 1)[0].strip()  # strip any inline comment
        if (n := _req_name(line)):
            names.add(n)
    return names


def main() -> int:
    declared = pyproject_direct_deps()
    installed = requirements_names()
    missing = sorted(declared - installed)
    if missing:
        print(
            "ERROR: apps/api/requirements.txt is missing direct dependencies "
            "declared in apps/api/pyproject.toml:\n"
        )
        for m in missing:
            print(f"  - {m}")
        print(
            "\nThe production Docker image installs from requirements.txt, so add "
            "the above (mirroring pyproject.toml) or prod will be missing them."
        )
        return 1
    print(f"OK: requirements.txt covers all {len(declared)} direct pyproject deps.")
    return 0


if __name__ == "__main__":
    sys.exit(main())