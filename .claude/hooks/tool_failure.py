#!/usr/bin/env python3
"""PostToolUseFailure (10/H17, H24): record each tool failure for the operating record. Silent."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import project_dir, read_payload, update_session  # noqa: E402


def main() -> None:
    try:
        payload = read_payload()
    except ValueError:
        return
    pd = project_dir(payload)
    error = str(payload.get("error", "")).strip().splitlines()
    entry = f"{time.strftime('%H:%M:%S')} {payload.get('tool_name', '?')}: {(error[0] if error else 'no message')[:200]}"
    update_session(pd, payload.get("session_id", ""), "failures", entry, append=True)


if __name__ == "__main__":
    main()
