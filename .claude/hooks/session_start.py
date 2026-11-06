#!/usr/bin/env python3
"""SessionStart (10/H15): inject the current truth, and record where the session started.

Prints (and Claude Code adds to context): tier, git state, the first part of docs/STATE.md,
the number of OPEN questions and the last check result. Records the starting HEAD and working-tree
state so the Stop gate can tell whether anything changed.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import git, project_dir, read_payload, state_dir, tier, update_session  # noqa: E402

STATE_CHARS = 4000


def main() -> None:
    try:
        payload = read_payload()
    except ValueError:
        payload = {}
    pd = project_dir(payload)
    sid = payload.get("session_id", "")
    head = (git(pd, "rev-parse", "HEAD") or "").strip()
    porcelain = git(pd, "status", "--porcelain")
    if payload.get("source", "startup") in ("startup", "clear") or not head:
        update_session(pd, sid, "start_head", head)
        update_session(pd, sid, "start_porcelain", porcelain)
        update_session(pd, sid, "started", time.strftime("%Y-%m-%dT%H:%M:%S"))

    lines = [f"[harness] tier {tier(pd)} · source {payload.get('source', 'startup')}"]
    branch = (git(pd, "branch", "--show-current") or "").strip()
    if branch:
        dirty = len([l for l in (porcelain or "").splitlines() if l.strip()])
        log = (git(pd, "log", "--oneline", "-3") or "").strip()
        lines.append(f"git: {branch}, {dirty} uncommitted path(s)\n{log}")
    else:
        lines.append("git: not a repository yet (run `git init -b main`).")

    state = pd / "docs" / "STATE.md"
    if state.is_file():
        text = state.read_text(errors="replace")
        lines.append("docs/STATE.md (dated current truth):\n" + text[:STATE_CHARS]
                     + ("\n[... truncated; read the file for the rest]" if len(text) > STATE_CHARS else ""))
    else:
        lines.append("docs/STATE.md is missing: create it before any feature work.")

    oq = pd / "docs" / "open-questions.md"
    if oq.is_file():
        n = len(re.findall(r"\|\s*OPEN\s*\|", oq.read_text(errors="replace")))
        lines.append(f"Open questions marked OPEN: {n} (nothing load-bearing is built on them).")
    last = state_dir(pd) / "last-check.txt"
    lines.append(f"Last check: {last.read_text().strip() if last.is_file() else 'not run in this checkout yet'}")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
