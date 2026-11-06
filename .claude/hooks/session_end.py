#!/usr/bin/env python3
"""SessionEnd (10/H24): write the session's operating record. Silent.

.claude/state/sessions/<session>.md: when, why it ended, tier, permission mode, MCP servers
allowlisted, files touched, tool failures, commits made, and whether docs/STATE.md was updated.
/end copies the relevant parts into the committed handoff.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import git, load_session, project_dir, read_payload, state_dir, tier  # noqa: E402


def main() -> None:
    try:
        payload = read_payload()
    except ValueError:
        payload = {}
    pd = project_dir(payload)
    sid = payload.get("session_id", "") or "unknown"
    s = load_session(pd, sid)
    try:
        mcp = sorted(json.loads((pd / ".mcp.json").read_text()).get("mcpServers", {}))
    except (OSError, ValueError):
        mcp = []
    head = (git(pd, "rev-parse", "HEAD") or "").strip()
    start = s.get("start_head") or ""
    commits = (git(pd, "log", "--oneline", f"{start}..HEAD") or "").strip() if start and head else ""
    touched = s.get("touched", [])
    record = [
        f"# Operating record: session {sid}",
        "",
        f"- Started: {s.get('started', '?')} · ended: {time.strftime('%Y-%m-%dT%H:%M:%S')} ({payload.get('reason', '?')})",
        f"- Tier: {tier(pd)} · permission mode: {payload.get('permission_mode', '?')}",
        f"- MCP servers allowlisted: {', '.join(mcp) or 'none'}",
        f"- Files touched: {', '.join(touched) or 'none'}",
        f"- Tool failures: {len(s.get('failures', []))}",
        f"- docs/STATE.md updated: {'yes' if 'docs/STATE.md' in touched else 'no'}",
        "- Commits this session:",
        *(f"  - {c}" for c in commits.splitlines()),
    ]
    d = state_dir(pd) / "sessions"
    d.mkdir(exist_ok=True)
    safe = "".join(c for c in sid if c.isalnum() or c in "-_")[:80] or "unknown"
    (d / f"{safe}.md").write_text("\n".join(record) + "\n")


if __name__ == "__main__":
    main()
