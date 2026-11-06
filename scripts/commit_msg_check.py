#!/usr/bin/env python3
"""commit-msg hook: Conventional Commits with a body that says why (11 §4).

Header: type(scope)!: summary, at most 72 characters. feat, fix, refactor and perf commits also need a
body (a blank line, then the why) except at tier P. Merge and revert messages from git pass unchanged.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

TYPES = "feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert"
HEADER = re.compile(rf"^({TYPES})(\([a-z0-9._/-]+\))?!?: \S.{{0,70}}$")
NEEDS_BODY = {"feat", "fix", "refactor", "perf"}
ROOT = Path(__file__).resolve().parents[1]


def tier() -> str:
    t = os.environ.get("HARNESS_TIER")
    if not t:
        try:
            t = json.loads((ROOT / ".claude" / "settings.json").read_text())["env"]["HARNESS_TIER"]
        except (OSError, KeyError, ValueError):
            t = "S"
    return t


def main(argv: list[str]) -> int:
    text = Path(argv[1]).read_text()
    lines = [l for l in text.splitlines() if not l.startswith("#")]
    header = lines[0].strip() if lines else ""
    if header.startswith(("Merge ", "Revert \"")):
        return 0
    if not HEADER.match(header):
        print(f"commit-msg: '{header}' is not a Conventional Commit header (type(scope): summary, ≤72 chars; "
              f"types: {TYPES.replace('|', ', ')}).")
        return 1
    kind = header.split("(")[0].split(":")[0].rstrip("!")
    body = "\n".join(lines[2:]).strip() if len(lines) > 2 and not lines[1].strip() else ""
    if kind in NEEDS_BODY and tier() != "P" and not body:
        print(f"commit-msg: a {kind} commit needs a body that says why (blank line after the header, then the reason).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
