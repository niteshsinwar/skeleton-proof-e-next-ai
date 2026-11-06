#!/usr/bin/env python3
"""Decide which CI jobs a change needs (11 §4 `changes`), failing closed: when in doubt, everything runs.

Prints `code=true|false` for $GITHUB_OUTPUT. A pull request whose every changed file is documentation outside the
harness (docs/**, or a Markdown file that no rule, skill or agent loads) may skip the build jobs; anything else, and
every push, merge-queue run or manual run, runs them all. The `gate` job treats a classifier skip as passed (11/GL3).

  python3 -I scripts/ci_changes.py --event pull_request --base <sha>
"""

from __future__ import annotations

import argparse
import subprocess
import sys

# Documentation that no build, test or harness reads. `.claude/**` is never here: rules and skills steer the agent.
DOC_ONLY_PREFIXES = ("docs/",)
DOC_ONLY_SUFFIXES = (".md",)
NEVER_DOC_ONLY = (".claude/", "CLAUDE.md", "AGENTS.md", "apps/", "ai/", "evals/", "ops/", ".github/", "scripts/")


def doc_only(path: str) -> bool:
    if path.startswith(NEVER_DOC_ONLY):
        return False
    return path.startswith(DOC_ONLY_PREFIXES) or path.endswith(DOC_ONLY_SUFFIXES)


def changed_files(base: str) -> list[str] | None:
    """Files changed since the merge base, or None when git can't say (then everything runs)."""
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"], capture_output=True, text=True, check=False  # noqa: S607
    )
    if result.returncode != 0:
        return None
    return [line for line in result.stdout.splitlines() if line.strip()]


def needs_code_jobs(event: str, base: str) -> tuple[bool, str]:
    if event != "pull_request" or not base:
        return True, f"{event or 'unknown'} event: everything runs"
    files = changed_files(base)
    if files is None:
        return True, "git could not list the changes: everything runs (fail closed)"
    if not files:
        return True, "no changed files listed: everything runs (fail closed)"
    code = [f for f in files if not doc_only(f)]
    if code:
        return True, f"{len(code)} of {len(files)} changed files are not documentation"
    return False, f"all {len(files)} changed files are documentation"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--event", default="")
    parser.add_argument("--base", default="")
    args = parser.parse_args()
    code, reason = needs_code_jobs(args.event, args.base)
    print(f"ci-changes: {reason}", file=sys.stderr)
    print(f"code={'true' if code else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
