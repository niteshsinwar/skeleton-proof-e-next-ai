#!/usr/bin/env python3
"""The GitHub workflows can't be quietly weakened (13/V5, 11 §4, 11/GL3). Stdlib only; zizmor adds the deep audit.

Every workflow: each third-party action pinned to a full 40-character commit SHA (a tag can be rewritten: trivy-action,
2026); a read-only token at the top level (jobs ask for more themselves); no `pull_request_target` (it runs with
secrets on code from a fork). ci.yml also: triggered by `merge_group` (or queued PRs never get their checks) and one
`gate` job that needs every other job, so it can be the single required check.

  python3 -I scripts/workflow_check.py      # exit 1 on any problem; prints how many files and actions it examined
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
USES = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)", re.M)
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


def jobs_of(text: str) -> dict[str, str]:
    """Job id -> its block, for the top-level `jobs:` mapping (two-space indented ids)."""
    match = re.search(r"^jobs:\s*$", text, re.M)
    if not match:
        return {}
    body = text[match.end():]
    ids = list(re.finditer(r"^  ([A-Za-z0-9_-]+):\s*$", body, re.M))
    return {m.group(1): body[m.end(): ids[i + 1].start() if i + 1 < len(ids) else len(body)] for i, m in enumerate(ids)}


def check_file(path: Path) -> tuple[list[str], int]:
    text = path.read_text(encoding="utf-8")
    name = path.relative_to(ROOT).as_posix()
    problems, actions = [], 0
    for use in USES.findall(text):
        if use.startswith(("./", "docker://")):
            continue
        actions += 1
        if not PINNED.match(use):
            problems.append(f"{name}: `{use}` is not pinned to a full commit SHA (13/V5)")
    if "pull_request_target" in text:
        problems.append(f"{name}: pull_request_target runs with secrets on a fork's code; never use it (13/V5)")
    top = text.split("\njobs:", 1)[0]
    if not re.search(r"^permissions:\s*\n\s+contents:\s*read\s*$", top, re.M) and not re.search(
        r"^permissions:\s*(read-all|\{\})\s*$", top, re.M
    ):
        problems.append(f"{name}: the top-level token must be read-only (`permissions: contents: read`, 13/V5)")
    if re.search(r"^permissions:\s*write-all", top, re.M):
        problems.append(f"{name}: write-all permissions (13/V5)")
    if path.name == "ci.yml":
        if not re.search(r"^\s+merge_group:", top, re.M):
            problems.append(f"{name}: no merge_group trigger, so queued pull requests never get their checks (W21)")
        jobs = jobs_of(text)
        if "gate" not in jobs:
            problems.append(f"{name}: no `gate` job to be the single required check (11/GL3)")
        else:
            needs = set(re.findall(r"[\w-]+", (re.search(r"needs:\s*\[([^\]]*)\]", jobs["gate"]) or [None, ""])[1]))
            missing = sorted(set(jobs) - {"gate"} - needs)
            if missing:
                problems.append(f"{name}: the gate does not need {missing}, so they could fail without blocking a merge")
            if "if: always()" not in jobs["gate"]:
                problems.append(f"{name}: the gate must run `if: always()`, or a failed job skips it and it never fails")
    return problems, actions


def main() -> int:
    files = sorted((ROOT / ".github" / "workflows").glob("*.y*ml"))
    problems, actions = [], 0
    for path in files:
        found, count = check_file(path)
        problems += found
        actions += count
    if not files:
        problems.append("no workflows found in .github/workflows: CI is not wired (10/H13)")
    print(f"workflow-check: examined {len(files)} workflows, {actions} third-party actions")
    for problem in problems:
        print(f"  - {problem}")
    print("workflow-check: " + ("FAIL" if problems else "pass"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
