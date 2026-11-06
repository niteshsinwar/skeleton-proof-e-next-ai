#!/usr/bin/env python3
"""Pre-commit granularity guard (10/H13): one decision per commit.

Refuses a commit that stages more than MAX_FILES files or touches more than MAX_AREAS top-level
areas (apps/<x> and packages/<x> count separately). Off at tier P. To override deliberately,
set COMMIT_GUARD_REASON="why this commit must be large"; the reason is printed for the record.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

MAX_FILES, MAX_AREAS = 12, 3
ROOT = Path(__file__).resolve().parents[1]


def tier() -> str:
    t = os.environ.get("HARNESS_TIER")
    if not t:
        try:
            t = json.loads((ROOT / ".claude" / "settings.json").read_text())["env"]["HARNESS_TIER"]
        except (OSError, KeyError, ValueError):
            t = "S"
    return t


def area(path: str) -> str:
    parts = path.split("/")
    if parts[0] in ("apps", "packages") and len(parts) > 2:
        return "/".join(parts[:2])
    return parts[0] if len(parts) > 1 else "(root)"


def main() -> int:
    if tier() == "P":
        return 0
    out = subprocess.run(["git", "diff", "--cached", "--name-only"], capture_output=True, text=True, cwd=ROOT)
    files = [f for f in out.stdout.splitlines() if f.strip()]
    areas = sorted({area(f) for f in files})
    if len(files) <= MAX_FILES and len(areas) <= MAX_AREAS:
        return 0
    reason = os.environ.get("COMMIT_GUARD_REASON", "").strip()
    summary = f"{len(files)} files across {len(areas)} areas ({', '.join(areas)})"
    if reason:
        print(f"commit-guard: override accepted for {summary}: {reason}")
        return 0
    print(f"commit-guard: {summary} exceeds {MAX_FILES} files / {MAX_AREAS} areas.\n"
          "Split it into one commit per decision, or set COMMIT_GUARD_REASON to say why it must be one.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
