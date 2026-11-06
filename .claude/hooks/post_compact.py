#!/usr/bin/env python3
"""Post-compact (10/H15), wired as SessionStart with matcher `compact` so its output reaches Claude.

Prints the breadcrumb that pre_compact.py left for this session, or a reminder if there is none.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import project_dir, read_payload, state_dir  # noqa: E402


def main() -> None:
    try:
        payload = read_payload()
    except ValueError:
        payload = {}
    pd = project_dir(payload)
    sid = payload.get("session_id", "") or "unknown"
    safe = "".join(c for c in sid if c.isalnum() or c in "-_")[:80] or "unknown"
    crumb = state_dir(pd) / "breadcrumbs" / f"{safe}.md"
    if crumb.is_file():
        print("[harness] Context was compacted. Breadcrumb from before compaction:\n" + crumb.read_text())
    else:
        print("[harness] Context was compacted and no breadcrumb was found: re-read docs/STATE.md and the "
              "current plan in docs/specs/ before continuing.")


if __name__ == "__main__":
    main()
