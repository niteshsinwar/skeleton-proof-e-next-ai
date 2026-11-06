#!/usr/bin/env python3
"""PreToolUse guard (10/H9, H10). Fails closed: an unreadable payload is denied.

Denies, across Read, Edit, Write, MultiEdit, NotebookEdit, Grep, Glob and Bash:
  * reading or writing secrets (.env*, keys, certificates; .env.example is allowed);
  * destructive git and shell commands, skipped hooks, and production deploys;
  * changes to protected records: an accepted ADR's body (only Status / Superseded-by lines may
    change) and any rewrite of ops/failure-log.md (append-only);
  * subagent scope breaches: test-author reading source, eval-author editing ai/, researcher
    writing outside .claude/reference/, reviewers writing anything.
Allowed calls produce no output.
"""
from __future__ import annotations

import difflib
import json
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import project_dir, read_payload, rel  # noqa: E402

SECRET_FILE = re.compile(
    r"(^|/)(\.env(\.(?!example$)[^/]+)?|[^/]*\.(pem|key|p12|pfx)|id_(rsa|ed25519|ecdsa|dsa)(\.[^/]*)?)$")
SECRET_DIR = re.compile(r"(^|/)(secrets|certs|\.dev-keys)(/|$)")
ADR = re.compile(r"^docs/decisions/(?!0000-)\d{4}-[^/]+\.md$")
FAILURE_LOG = "ops/failure-log.md"
STATUS_LINE = re.compile(r"^\s*(\*\*)?(Status|Superseded by)\b", re.I)

DESTRUCTIVE = [
    (re.compile(r"\bgit\s+push\b[^;&|]*\s(--force(-with-lease)?|-f)\b"), "force-push rewrites shared history"),
    (re.compile(r"\bgit\s+reset\s+--hard\b"), "git reset --hard discards work"),
    (re.compile(r"\bgit\s+clean\s+-[a-zA-Z]*f"), "git clean -f deletes untracked files"),
    (re.compile(r"\bgit\s+add\s+(-A|--all)\b|\bgit\s+add\s+\.(\s|$)"), "stage explicit paths, never everything (10/H13)"),
    (re.compile(r"\bgit\s+(commit|push)\b[^;&|]*--no-verify\b"), "hooks are never skipped"),
    (re.compile(r"\bgit\s+(checkout\s+(--\s+)?\.|restore\s+\.)(\s|$)"), "discarding all changes is never automatic"),
    (re.compile(r"\b(deploy|release|promote)\b[^;&|]*\b(prod|production)\b|--env(ironment)?[= ](prod|production)\b"),
     "a production deploy is a human action (07/O3)"),
]
RM_RF = re.compile(r"\brm\s+(-[a-zA-Z]*[rR][a-zA-Z]*\s+)+(.*)")
WRITE_OPS = re.compile(r"\bsed\s+(-[a-zA-Z]*\s+)*-i|\bperl\s+-[a-zA-Z]*i|(?<![>\d&])>(?!>)|\btee\b(?!\s+-a)|\bmv\b|\brm\b|\bcp\b|\btruncate\b")
APPEND_OK_WRITE_OPS = re.compile(r"\bsed\s+(-[a-zA-Z]*\s+)*-i|\bperl\s+-[a-zA-Z]*i|(?<![>\d&])>(?!>)|\btee\b(?!\s+-a)|\bmv\b|\brm\b|\bcp\b|\btruncate\b")


def deny(reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": f"[protect] {reason}"}}))
    sys.exit(0)


def is_secret(path: str) -> bool:
    return bool(SECRET_FILE.search(path) or SECRET_DIR.search(path))


def only_status_lines_changed(old: str, new: str) -> bool:
    for line in difflib.ndiff(old.splitlines(), new.splitlines()):
        if line[:2] in ("+ ", "- ") and line[2:].strip() and not STATUS_LINE.match(line[2:]):
            return False
    return True


def accepted(text: str) -> bool:
    return any(STATUS_LINE.match(l) and re.search(r"\baccepted\b", l, re.I) for l in text.splitlines())


def check_records(pd: Path, path: str, tool: str, ti: dict) -> None:
    target = pd / path
    current = target.read_text(errors="replace") if target.is_file() else ""
    edits = []
    if tool == "Write":
        edits = [(current, ti.get("content", ""))]
    elif tool == "Edit":
        edits = [(ti.get("old_string", ""), ti.get("new_string", ""))]
    elif tool == "MultiEdit":
        edits = [(e.get("old_string", ""), e.get("new_string", "")) for e in ti.get("edits", [])]
    elif tool == "NotebookEdit":
        return
    if ADR.match(path) and accepted(current):
        for old, new in edits:
            if not only_status_lines_changed(old, new):
                deny(f"{path} is an accepted ADR: only its Status and Superseded-by lines may change. "
                     "Write a new ADR that supersedes it.")
    if path == FAILURE_LOG and current:
        for old, new in edits:
            if not new.startswith(old):
                deny(f"{FAILURE_LOG} is append-only: add a new entry instead of changing an old one.")


def check_bash(pd: Path, cmd: str) -> None:
    flat = re.sub(r"\d?>&\d|&>", " ", cmd)
    for rx, why in DESTRUCTIVE:
        if rx.search(flat):
            deny(f"blocked command: {why}. Ask the user to run it themselves if it is really intended.")
    try:
        tokens = shlex.split(flat, posix=True)
    except ValueError:
        tokens = flat.split()
    for tok in tokens:
        tok = tok.strip("'\"<>|;&()")
        if tok and not tok.startswith("-") and is_secret(tok):
            deny(f"the command touches a secret ({tok}). Secrets are never read by agents (05/SG12).")
    for m in RM_RF.finditer(flat):
        for target in m.group(2).split():
            if target.startswith("-"):
                continue
            t = target.strip("'\"")
            r = rel(pd, t) or t
            if t in ("/", "~", ".", "..", "*", "./*", "$HOME", "${HOME}") or r.startswith("/") or r.startswith(".."):
                deny(f"rm -r on '{t}' would delete outside a specific project path.")
    if re.search(r"docs/decisions/\d{4}-", flat) and WRITE_OPS.search(flat):
        deny("shell writes to ADR files are blocked; edit with the Edit tool (accepted ADRs are immutable).")
    if FAILURE_LOG in flat and APPEND_OK_WRITE_OPS.search(flat):
        deny(f"{FAILURE_LOG} is append-only; use >> or tee -a, never overwrite.")


def check_agent_scope(agent: str, tool: str, path: str | None) -> None:
    writes = tool in ("Edit", "Write", "MultiEdit", "NotebookEdit", "Bash")
    if agent in ("spec-reviewer", "security-reviewer") and writes:
        deny(f"{agent} is read-only.")
    if agent == "test-author":
        if tool in ("Read", "Grep", "Glob") and (path is None or re.match(r"^apps/[^/]+/src(/|$)", path)):
            deny("test-author writes tests from the spec without seeing the implementation (06/T2); "
                 "give a path outside apps/*/src.")
    if agent == "eval-author" and writes and path and re.match(r"^ai(/|$)", path):
        deny("eval-author cannot edit the prompts it grades (06/E1).")
    if agent == "researcher" and tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        if not (path or "").startswith(".claude/reference/"):
            deny("researcher writes only to .claude/reference/.")


def main() -> None:
    try:
        payload = read_payload()
    except (ValueError, json.JSONDecodeError) as exc:
        deny(f"unreadable hook payload ({exc}); failing closed.")
        return
    pd = project_dir(payload)
    tool = payload.get("tool_name", "")
    ti = payload.get("tool_input") or {}
    raw_path = ti.get("file_path") or ti.get("notebook_path") or ti.get("path")
    path = rel(pd, raw_path)
    agent = payload.get("agent_type") or ""

    if agent:
        check_agent_scope(agent, tool, path)
    if tool == "Bash":
        check_bash(pd, ti.get("command", ""))
        return
    if path and is_secret(path):
        deny(f"{path} is a secret. Secrets are never read or written by agents (05/SG12).")
    if tool == "Glob" and is_secret(ti.get("pattern", "")):
        deny("searching for secret files is blocked.")
    if path and tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        check_records(pd, path, tool, ti)


if __name__ == "__main__":
    main()
