#!/usr/bin/env python3
"""PostToolUse on Edit/Write/MultiEdit (10/H2, H24).

Records the touched file for the session's operating record. If the file is a rule under
.claude/rules/, validates its `paths:` frontmatter at once, because invalid YAML silently loads the
rule everywhere; a broken header is the one thing this hook reports. Otherwise it is silent.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import project_dir, read_payload, rel, update_session  # noqa: E402


def main() -> None:
    try:
        payload = read_payload()
    except ValueError:
        return
    pd = project_dir(payload)
    ti = payload.get("tool_input") or {}
    path = rel(pd, ti.get("file_path"))
    if not path:
        return
    update_session(pd, payload.get("session_id", ""), "touched", path, append=True)
    if path.startswith(".claude/rules/") and path.endswith(".md"):
        checker = pd / "scripts" / "harness_check.py"
        r = subprocess.run([sys.executable, "-I", str(checker), "--rule", path], cwd=pd,
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            print(json.dumps({"decision": "block",
                              "reason": f"[post-edit] {path} has an invalid header: {r.stdout.strip()} "
                                        "(a broken `paths:` block loads the rule everywhere)."}))


if __name__ == "__main__":
    main()
