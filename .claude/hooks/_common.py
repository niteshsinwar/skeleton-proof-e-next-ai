"""Shared helpers for the harness hooks (standard library only, 10/H12).

Every hook reads one JSON object from stdin (the hook payload) and finds the project through
CLAUDE_PROJECT_DIR. Session state lives in .claude/state/ (gitignored).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


def read_payload() -> dict:
    """Parse the hook payload. Raises ValueError on anything that isn't a JSON object."""
    raw = sys.stdin.read()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("payload is not a JSON object")
    return data


def project_dir(payload: dict | None = None) -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env).resolve()
    if payload and payload.get("cwd"):
        return Path(payload["cwd"]).resolve()
    return Path.cwd().resolve()


def tier(pd: Path) -> str:
    """HARNESS_TIER from the environment, else from .claude/settings.json, else S (the safer default)."""
    t = os.environ.get("HARNESS_TIER")
    if not t:
        try:
            t = json.loads((pd / ".claude" / "settings.json").read_text())["env"]["HARNESS_TIER"]
        except (OSError, KeyError, ValueError, TypeError):
            t = "S"
    return t if t in ("P", "S", "E") else "S"


def state_dir(pd: Path) -> Path:
    d = pd / ".claude" / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _session_path(pd: Path, sid: str) -> Path:
    safe = "".join(c for c in (sid or "unknown") if c.isalnum() or c in "-_")[:80] or "unknown"
    d = state_dir(pd) / "sessions"
    d.mkdir(exist_ok=True)
    return d / f"{safe}.json"


def load_session(pd: Path, sid: str) -> dict:
    try:
        return json.loads(_session_path(pd, sid).read_text())
    except (OSError, ValueError):
        return {}


def save_session(pd: Path, sid: str, data: dict) -> None:
    p = _session_path(pd, sid)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
    os.replace(tmp, p)  # atomic: a reader never sees a half-written file


def update_session(pd: Path, sid: str, key: str, value, append: bool = False) -> None:
    data = load_session(pd, sid)
    if append:
        items = data.setdefault(key, [])
        if value not in items:
            items.append(value)
    else:
        data[key] = value
    data["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    save_session(pd, sid, data)


def git(pd: Path, *args: str) -> str | None:
    """Run git in the project; None if this isn't a git repository or git fails."""
    try:
        r = subprocess.run(["git", *args], cwd=pd, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def rel(pd: Path, path: str | None) -> str | None:
    """Project-relative POSIX path, or the absolute path if it lies outside the project."""
    if not path:
        return None
    p = Path(path)
    if not p.is_absolute():
        p = pd / p
    p = Path(os.path.normpath(p))
    try:
        return p.relative_to(pd).as_posix()
    except ValueError:
        return p.as_posix()
