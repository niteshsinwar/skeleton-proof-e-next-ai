#!/usr/bin/env python3
"""Stop gate (10/H11, 10 §4). Blocks only on mechanical certainties.

* Nothing changed since the session started → stay silent (nothing to verify).
* `make check` red → tier P warns; tiers S and E block with the failing output.
* Commits made this session but docs/STATE.md untouched → S warns; E blocks once (run /end).
Never blocks twice in a row: when stop_hook_active is set, it lets Claude stop.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import git, load_session, project_dir, read_payload, state_dir, tier  # noqa: E402


def emit(obj: dict) -> None:
    print(json.dumps(obj))
    sys.exit(0)


def main() -> None:
    try:
        payload = read_payload()
    except ValueError:
        payload = {}
    if payload.get("stop_hook_active"):
        sys.exit(0)
    pd = project_dir(payload)
    t = tier(pd)
    session = load_session(pd, payload.get("session_id", ""))
    head = (git(pd, "rev-parse", "HEAD") or "").strip()
    porcelain = git(pd, "status", "--porcelain")
    if porcelain is not None and session.get("start_head") == head and session.get("start_porcelain") == porcelain:
        sys.exit(0)

    try:
        r = subprocess.run(["make", "-s", "check"], cwd=pd, capture_output=True, text=True, timeout=540)
        ok, out = r.returncode == 0, (r.stdout + r.stderr)
    except (OSError, subprocess.TimeoutExpired) as exc:
        ok, out = False, f"make check could not run: {exc}"
    stamp = time.strftime("%Y-%m-%d %H:%M")
    (state_dir(pd) / "last-check.txt").write_text(f"{stamp} make check: {'green' if ok else 'RED'}\n")

    if not ok:
        tail = "\n".join(out.strip().splitlines()[-25:])
        msg = f"make check is red (tier {t}). Last lines:\n{tail}"
        if t == "P":
            emit({"systemMessage": f"[stop-gate] {msg}"})
        emit({"decision": "block", "reason": f"[stop-gate] {msg}\nFix it, or record why in docs/STATE.md and ask."})

    start = session.get("start_head")
    if start and head and start != head and t in ("S", "E"):
        changed = git(pd, "diff", "--name-only", f"{start}..HEAD") or ""
        dirty = porcelain or ""
        if "docs/STATE.md" not in changed and "docs/STATE.md" not in dirty:
            msg = "commits were made this session but docs/STATE.md was not updated; run /end (10/H15)."
            if t == "E":
                emit({"decision": "block", "reason": f"[stop-gate] {msg}"})
            emit({"systemMessage": f"[stop-gate] {msg}"})


if __name__ == "__main__":
    main()
