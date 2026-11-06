#!/usr/bin/env python3
"""Fail on a breaking change to the API contract (02/A10): the committed OpenAPI snapshot at a base commit against
the one in this tree, with oasdiff (pinned in ops/tools.toml; `make tools`).

    python3 -I scripts/api_diff.py --base origin/main     # make api-diff BASE=origin/main; CI passes the PR's base

A breaking change (oasdiff level ERR: a removed route, a new required field, a narrowed type, ...) fails unless the
old route was retired first and its sunset has passed (`api/deprecation.py`, `x-sunset`). Warnings are printed and
do not fail. No snapshot at the base means a first contract: said so, nothing compared. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = "packages/contracts/openapi.json"
OASDIFF = ROOT / ".tools" / "bin" / "oasdiff"
METHODS = {"get", "put", "post", "delete", "patch", "head", "options", "trace"}


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)


def operations(spec: dict) -> int:
    return sum(1 for item in spec.get("paths", {}).values() for method in item if method in METHODS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="the git ref to compare with: origin/main, or a PR's base SHA")
    base = parser.parse_args().base.strip()
    if not base:
        print("api-diff: no base given (make api-diff BASE=origin/main)")
        return 2
    if set(base) == {"0"}:  # GitHub's `before` on the first push of a branch: there is nothing earlier
        print("api-diff: the first push of a branch has no earlier commit; nothing compared")
        return 0
    if git("cat-file", "-e", f"{base}^{{commit}}").returncode != 0:
        print(f"api-diff: {base} is not a commit in this clone (CI needs the history: fetch-depth: 0)")
        return 2
    current = ROOT / SPEC
    if not current.is_file():
        print(f"api-diff: {SPEC} is missing; run `make contracts` and commit it")
        return 2
    old = git("show", f"{base}:{SPEC}")
    if old.returncode != 0:
        print(f"api-diff: no {SPEC} at {base[:12]}: this is the first contract; nothing compared")
        return 0
    if not OASDIFF.is_file():
        print("api-diff: oasdiff is not installed; run `make tools`")
        return 2
    run = subprocess.run([str(OASDIFF), "breaking", "--fail-on", "ERR", f"{base}:{SPEC}", SPEC], cwd=ROOT,
                         capture_output=True, text=True, check=False)
    print(run.stdout.strip() or "(no changes reported)")
    if run.stderr.strip():
        print(run.stderr.strip(), file=sys.stderr)
    before, after = operations(json.loads(old.stdout)), operations(json.loads(current.read_text()))
    counts = f"{before} operations at {base[:12]}, {after} now"
    if run.returncode not in (0, 1):
        print(f"api-diff: oasdiff failed (exit {run.returncode}); {counts}")
        return 2
    verdict = "no breaking change" if run.returncode == 0 else "BREAKING: add a new version, retire the old (02/A10)"
    print(f"api-diff: compared {counts}: {verdict}")
    return run.returncode


if __name__ == "__main__":
    sys.exit(main())
