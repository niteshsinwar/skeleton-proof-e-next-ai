#!/usr/bin/env python3
"""PreCompact (10/H15): leave a breadcrumb so the plan survives compaction.

Writes .claude/state/breadcrumbs/<session>.md with the files touched, the newest plan on disk,
the last check result and the git state. post_compact.py reads it back after compaction.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import git, load_session, project_dir, read_payload, state_dir  # noqa: E402


def main() -> None:
    try:
        payload = read_payload()
    except ValueError:
        payload = {}
    pd = project_dir(payload)
    sid = payload.get("session_id", "") or "unknown"
    session = load_session(pd, sid)
    plans = sorted((pd / "docs" / "specs").glob("*/plan.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    last = state_dir(pd) / "last-check.txt"
    body = [
        f"# Breadcrumb before compaction ({time.strftime('%Y-%m-%d %H:%M')}, trigger: {payload.get('trigger', '?')})",
        "",
        f"- Newest plan on disk: {plans[0].relative_to(pd).as_posix() if plans else 'none'}",
        f"- Files touched this session: {', '.join(session.get('touched', [])) or 'none recorded'}",
        f"- Tool failures this session: {len(session.get('failures', []))}",
        f"- Last check: {last.read_text().strip() if last.is_file() else 'not run'}",
        f"- git: {(git(pd, 'status', '--short') or 'not a repository').strip() or 'clean'}",
        "",
        "Re-read docs/STATE.md and the plan before continuing.",
    ]
    d = state_dir(pd) / "breadcrumbs"
    d.mkdir(exist_ok=True)
    safe = "".join(c for c in sid if c.isalnum() or c in "-_")[:80] or "unknown"
    (d / f"{safe}.md").write_text("\n".join(body) + "\n")


if __name__ == "__main__":
    main()
