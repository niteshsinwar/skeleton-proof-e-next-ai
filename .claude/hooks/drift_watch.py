#!/usr/bin/env python3
"""UserPromptSubmit (10/H15): silent unless docs/STATE.md has drifted behind HEAD.

Warns once per prompt when STATE.md was last committed more than DRIFT_LIMIT commits ago.
Outside a git repository, or when STATE is current, it prints nothing (10/H11).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import git, project_dir, read_payload  # noqa: E402

DRIFT_LIMIT = 15


def main() -> None:
    try:
        payload = read_payload()
    except ValueError:
        payload = {}
    pd = project_dir(payload)
    total = git(pd, "rev-list", "--count", "HEAD")
    if total is None:
        return
    last = (git(pd, "log", "-1", "--format=%H", "--", "docs/STATE.md") or "").strip()
    behind = int((git(pd, "rev-list", "--count", f"{last}..HEAD") if last else total) or 0)
    if behind > DRIFT_LIMIT:
        print(f"[drift-watch] docs/STATE.md is {behind} commits behind HEAD; update it (or run /end) "
              "before the next handoff.")


if __name__ == "__main__":
    main()
