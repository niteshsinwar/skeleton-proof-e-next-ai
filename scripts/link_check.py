#!/usr/bin/env python3
"""Every relative link in the project's Markdown leads somewhere: the file exists and its #anchor is a heading.

Offline and standard library only, so it is cheap enough for every nightly run. External (http, mailto) links are
not fetched: they fail for reasons outside the repository and would make the check flaky.

  python3 -I scripts/link_check.py                 # exit 1 on a broken link; prints how many files and links it saw
  python3 -I scripts/link_check.py --root DIR      # another tree (tests)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "node_modules", ".venv", ".next", "dist", ".tools", ".render", "__pycache__", "playwright-report"}
LINK = re.compile(r"(?<!!)\[[^\]\n]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
FENCE = re.compile(r"^\s*(```|~~~)")


def slug(heading: str) -> str:
    """GitHub's heading anchors: lower case, punctuation dropped, spaces to hyphens."""
    text = re.sub(r"[`*]|\[([^\]]*)\]\([^)]*\)", r"\1", heading.strip().lower())
    return re.sub(r"\s", "-", re.sub(r"[^\w\s-]", "", text))


def anchors(path: Path) -> set[str]:
    found, in_code = set(), False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if FENCE.match(line):
            in_code = not in_code
        elif not in_code and (m := re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line)):
            found.add(slug(m.group(1)))
    return found


def links(path: Path) -> list[tuple[int, str]]:
    out, in_code = [], False
    for no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if FENCE.match(line):
            in_code = not in_code
            continue
        if not in_code:
            out += [(no, m.group(1)) for m in LINK.finditer(re.sub(r"`[^`]*`", "", line))]
    return out


def check(root: Path) -> tuple[list[str], int, int]:
    files = [p for p in sorted(root.rglob("*.md")) if not SKIP_DIRS & set(p.relative_to(root).parts)]
    problems, count = [], 0
    for md in files:
        for no, target in links(md):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):  # http:, https:, mailto: ...
                continue
            count += 1
            path, _, anchor = target.partition("#")
            dest = (md.parent / path).resolve() if path else md
            where = f"{md.relative_to(root)}:{no}"
            if not dest.exists():
                problems.append(f"{where}: [{target}] leads to a file that doesn't exist")
            elif anchor and dest.suffix == ".md" and anchor not in anchors(dest):
                problems.append(f"{where}: [{target}] names a heading #{anchor} that {dest.name} doesn't have")
    return problems, len(files), count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    problems, files, count = check(parser.parse_args().root.resolve())
    print(f"link-check: examined {files} Markdown files, {count} relative links")
    for problem in problems:
        print(f"  - {problem}")
    if files == 0:
        problems.append("no Markdown files examined")
    print("link-check: " + ("FAIL" if problems else "pass"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
