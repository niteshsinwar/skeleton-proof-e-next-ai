"""Mutation check: proves the tests on critical paths can catch a real fault (06/T7, 06/EL4).

Each entry in scripts/mutations.toml plants one fault by editing a file, runs the test named for it, and requires the
test to FAIL with the expected text in its output: the proof is the failure message, not just the red. Every edit is
reverted by writing the original bytes back, never with `git checkout`, and bytecode is off, so nothing stale runs.

Exit 1 if any fault survives, if an entry's code is no longer found (the list is stale), or if a database fault
can't run while REQUIRE_DB=1. Prints the size of the set it examined (10/H18).

    make mutation                       every entry
    make mutation ARGS="--only <name>"  one entry
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = "uv run pytest -x -q -p no:cacheprovider"  # override with MUTATION_RUNNER (the harness tests do)


def run_one(entry: dict[str, str], runner: list[str]) -> tuple[str, str]:
    target = ROOT / entry["file"]
    original = target.read_bytes()
    text = original.decode()
    if text.count(entry["find"]) != 1:
        return "stale", f"the code to mutate was found {text.count(entry['find'])} times in {entry['file']}, not once"
    try:
        target.write_text(text.replace(entry["find"], entry["replace"], 1), encoding="utf-8")
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        r = subprocess.run(
            [*runner, entry["test"]], cwd=ROOT / entry.get("cwd", "apps/api"), env=env, capture_output=True, text=True,
            timeout=600,
        )  # fmt: skip
    finally:
        target.write_bytes(original)  # reverted by edit, whatever happened
    output = r.stdout + r.stderr
    if r.returncode == 0:
        return "survived", "the test passed with the fault in place"
    if entry["expect"] not in output:
        return "survived", f"the test failed, but not with {entry['expect']!r}: it failed for another reason"
    return "caught", entry["expect"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", help="run one entry by name")
    ap.add_argument("--list", default=str(ROOT / "scripts" / "mutations.toml"))
    args = ap.parse_args()
    entries = tomllib.loads(Path(args.list).read_text(encoding="utf-8")).get("mutation", [])
    if args.only:
        entries = [e for e in entries if e["name"] == args.only]
    has_db = bool(os.environ.get("TEST_DATABASE_URL"))
    runner = shlex.split(os.environ.get("MUTATION_RUNNER", RUNNER))
    counts = {"caught": 0, "survived": 0, "stale": 0, "skipped": 0}
    for e in entries:
        if e.get("lane") == "integration" and not has_db:
            if os.environ.get("REQUIRE_DB") == "1":
                print(f"FAIL     {e['name']}: needs TEST_DATABASE_URL and REQUIRE_DB=1 forbids skipping")
                counts["stale"] += 1
            else:
                print(f"skipped  {e['name']}: needs TEST_DATABASE_URL")
                counts["skipped"] += 1
            continue
        result, detail = run_one(e, runner)
        counts[result] += 1
        print(f"{result:<8} {e['name']}: {detail}")
    print(f"mutation: examined {len(entries)} faults: " + ", ".join(f"{v} {k}" for k, v in counts.items()))
    if not entries:
        print("mutation: nothing was examined, which proves nothing")
        return 1
    return 1 if counts["survived"] or counts["stale"] else 0


if __name__ == "__main__":
    sys.exit(main())
