#!/usr/bin/env python3
"""Notes about tools' behaviour are re-verified within 21 days (10/H17). Standard library only; run nightly.

Each note in .claude/reference/ (except the README and the generated baseline-rules.md) carries the date it was last
checked against its source, written as `verified YYYY-MM-DD` (any case). The newest such date counts. A note with
no date, or whose newest date is more than 21 days old, fails: re-read its sources, correct it, and update the date.

  python3 -I scripts/reference_freshness.py                  # exit 1 on a stale or undated note
  python3 -I scripts/reference_freshness.py --today 2026-12-01   # check as of another day (tests)
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_AGE_DAYS = 21
SKIP = {"README.md", "baseline-rules.md"}  # the index, and a pinned copy of the baseline (refreshed by copier update)
VERIFIED = re.compile(r"\bverified\b[^0-9\n]{0,40}?(\d{4}-\d{2}-\d{2})", re.I)


def check(folder: Path, today: date) -> tuple[list[str], int]:
    notes = sorted(p for p in folder.glob("*.md") if p.name not in SKIP)
    problems = []
    for note in notes:
        dates = [date.fromisoformat(d) for d in VERIFIED.findall(note.read_text(encoding="utf-8"))]
        if not dates:
            problems.append(f"{note.name}: no `verified YYYY-MM-DD` date, so nobody can tell when it was last true")
            continue
        age = (today - max(dates)).days
        if age > MAX_AGE_DAYS:
            problems.append(f"{note.name}: verified {max(dates)}, {age} days ago (limit {MAX_AGE_DAYS}, 10/H17); "
                            "re-read its sources and update it")
    return problems, len(notes)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--today", type=date.fromisoformat, default=date.today())
    parser.add_argument("--dir", type=Path, default=ROOT / ".claude" / "reference")
    args = parser.parse_args(argv[1:])
    problems, count = check(args.dir, args.today)
    if count == 0:
        problems.append(f"{args.dir}: no reference notes examined, so the check saw nothing (10/H18)")
    print(f"reference-freshness: examined {count} notes as of {args.today}")
    for problem in problems:
        print(f"  - {problem}")
    print("reference-freshness: " + ("FAIL" if problems else "pass"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
