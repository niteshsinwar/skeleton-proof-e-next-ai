#!/usr/bin/env python3
"""Counted status (12/N9): every number here is counted from the repository, never estimated.

Quote this output in docs/STATE.md instead of writing percentages.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def count(pattern: str, text: str) -> int:
    return len(re.findall(pattern, text, re.M))


def read(p: str) -> str:
    f = ROOT / p
    return f.read_text(errors="replace") if f.is_file() else ""


def main() -> None:
    adrs = sorted((ROOT / "docs" / "decisions").glob("[0-9][0-9][0-9][0-9]-*.md"))
    adrs = [a for a in adrs if not a.name.startswith("0000-")]
    by_status: dict[str, int] = {}
    for a in adrs:
        m = re.search(r"^\*\*Status:\*\*\s*([A-Za-z]+)", a.read_text(errors="replace"), re.M)
        key = m.group(1).capitalize() if m else "Unknown"
        by_status[key] = by_status.get(key, 0) + 1
    scope = read("docs/SCOPE.md")
    scope_done = count(r"^\| S\d+ \|[^|]*\|[^|]*\|\s*done\s*\|", scope)
    scope_total = count(r"^\| S\d+", scope)
    rules = list((ROOT / ".claude" / "rules").glob("*.md"))
    scoped = sum(1 for r in rules if r.read_text().startswith("---"))
    adr_summary = ", ".join(k + " " + str(v) for k, v in sorted(by_status.items())) or "none"
    tests = [p for p in ROOT.rglob("test_*.py") if ".venv" not in p.parts and "node_modules" not in p.parts]
    evals = len(list((ROOT / "evals" / "datasets").glob("*/*"))) if (ROOT / "evals").is_dir() else "no evals/ yet"
    rows = [
        ("Decisions (ADRs)", f"{len(adrs)} ({adr_summary})"),
        ("Open questions marked OPEN", count(r"\|\s*OPEN\s*\|", read("docs/open-questions.md"))),
        ("Scope rows done / total", f"{scope_done} / {scope_total}"),
        ("Failure-log entries", count(r"^## F-\d+", read("ops/failure-log.md"))),
        ("Rules (always / path-scoped)", f"{len(rules) - scoped} / {scoped}"),
        ("Workflow skills", len(list((ROOT / ".claude" / "skills").glob("*/SKILL.md")))),
        ("Subagents", len(list((ROOT / ".claude" / "agents").glob("*.md")))),
        ("Test files", len(tests)),
        ("Eval dataset releases", evals),
    ]
    width = max(len(k) for k, _ in rows)
    for k, v in rows:
        print(f"{k:<{width}}  {v}")


if __name__ == "__main__":
    main()
