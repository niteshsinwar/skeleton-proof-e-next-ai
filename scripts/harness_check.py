#!/usr/bin/env python3
"""Harness integrity check (10/H1–H5, H12, H21; 12/N8). Standard library only.

  python3 -I scripts/harness_check.py            full check, prints what it examined
  python3 -I scripts/harness_check.py --rule F   validate one rule file's header (used by post_edit.py)

Exit 0 = pass, 1 = at least one failure (each printed).
"""
from __future__ import annotations

import difflib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALWAYS_LOADED = ["00-invariants.md", "10-session.md", "20-git-and-decisions.md", "30-verify-and-report.md", "40-research.md"]
CONTRACT = ["Load first", "Run", "Same commit", "Prove", "Never"]
# Areas scaffolded by later build phases: references into them are "pending" until the folder exists.
AREAS = ["apps/api", "apps/web", "packages/contracts", "ai", "evals", "infra", "tests"]
# Runtime state the hooks create on first use (gitignored), so it never exists in a fresh checkout.
RUNTIME = (".claude/state",)
REF_ROOTS = ("docs/", ".claude/", "ops/", "scripts/", "apps/", "packages/", "ai/", "evals/", "tests/", "infra/")
REF_FILES = {"Makefile", "CLAUDE.md", "AGENTS.md", ".mcp.json", "README.md"}
SKILL_VOCAB = {
    "start", "end", "status", "adr", "failure-log", "discover", "feature", "endpoint", "screen", "data-model",
    "integration", "ai-step", "threat-model", "review", "audit", "check-fixtures", "scorecard", "release",
}
CLAUDE_MAX_LINES, CLAUDE_MAX_BYTES, ALWAYS_MAX_BYTES = 120, 6 * 1024, 32 * 1024
SECRET_DENIES = {"Read(.env)", "Read(.env.*)", "Read(*.pem)", "Read(*.key)"}


STATUS_LINE = re.compile(r"^\s*(\*\*)?(Status|Superseded by)\b", re.I)


def _git(*args: str) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def _accepted(text: str) -> bool:
    return any(STATUS_LINE.match(l) and re.search(r"\baccepted\b", l, re.I) for l in text.splitlines())


def _body(text: str) -> list[str]:
    return [l for l in text.splitlines() if l.strip() and not STATUS_LINE.match(l)]


def history_check(fails: list[str]) -> int:
    """10/H10: back up the protect hook for paths computed at runtime, from git history.

    An accepted ADR's body never changes after the commit that accepted it; the failure log only grows.
    Returns how many records were checked (0 outside a git repository).
    """
    if _git("rev-parse", "--is-inside-work-tree") is None:
        return 0
    checked = 0
    for adr in sorted((ROOT / "docs" / "decisions").glob("[0-9][0-9][0-9][0-9]-*.md")):
        if adr.name.startswith("0000-"):
            continue
        rel = adr.relative_to(ROOT).as_posix()
        for h in (_git("log", "--format=%H", "--reverse", "--", rel) or "").split():
            then = _git("show", f"{h}:{rel}") or ""
            if _accepted(then):
                checked += 1
                if _body(then) != _body(adr.read_text()):
                    diff = [l for l in difflib.unified_diff(_body(then), _body(adr.read_text()), lineterm="", n=0)
                            if l[:1] in "+-" and not l.startswith(("+++", "---"))][:3]
                    fails.append(f"{rel}: accepted in {h[:7]} but its body has changed since: {diff} (10/H10)")
                break
    log = "ops/failure-log.md"
    prev = ""
    for h in (_git("log", "--format=%H", "--reverse", "--", log) or "").split():
        cur = _git("show", f"{h}:{log}") or ""
        checked += 1
        if not cur.startswith(prev):
            fails.append(f"{log} was rewritten in commit {h[:7]}; it is append-only (10/H10, H17)")
        prev = cur
    current = (ROOT / log).read_text() if (ROOT / log).is_file() else ""
    if prev and not current.startswith(prev):
        fails.append(f"{log} has uncommitted edits to existing entries; it is append-only")
    return checked


def parse_rule_header(text: str) -> tuple[list[str] | None, str | None]:
    """Return (globs, error). No front-matter → (None, None): the rule is unscoped.

    Deliberately strict: the only accepted form is
        ---
        paths:
          - "glob"
        ---
    because a header Claude Code can't parse silently loads the rule everywhere.
    """
    if not text.startswith("---\n"):
        return None, None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None, "front-matter is not closed by a '---' line"
    lines = text[4:end].split("\n")
    if lines[0] != "paths:":
        return None, "the only allowed key is `paths:` on the first line"
    globs = []
    for line in lines[1:]:
        m = re.fullmatch(r'  - "([^"\s]+)"', line)
        if not m:
            return None, f"bad paths entry {line!r} (expected:   - \"glob\")"
        globs.append(m.group(1))
    if not globs:
        return None, "`paths:` lists no globs"
    return globs, None


def fm_fields(text: str) -> dict[str, str]:
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        return {}
    block = text[4:text.index("\n---\n", 4)]
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"^([A-Za-z-]+):\s*(.*)$", block, re.M)}


def glob_match(path: str, pattern: str) -> bool:
    """Match like the rule loader does: `*` stays inside one folder, `**/` spans any number of folders."""
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pattern[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.fullmatch(out, path) is not None


def compose_services(path: Path) -> list[str]:
    """Service names under the top-level `services:` key, read without a YAML library (stdlib only)."""
    if not path.is_file():
        return []
    names, inside = [], False
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith((" ", "\t")):
            inside = line.rstrip() == "services:"
            continue
        match = re.match(r"^  ([A-Za-z0-9_.-]+):\s*$", line)
        if inside and match:
            names.append(match.group(1))
    return names


STEP = re.compile(r"^### (\d+)\. (.+)$")
PIPED_OUTPUT = re.compile(r"\|\s*(tail|head)\b")
EXIT_READ = re.compile(r'^\s*echo\s+"?(exit\s*[=:]\s*)?\$\?"?\s*$')
# 07/O17: the response every incident follows, and the AI incidents the runbook must cover when the product has AI.
INCIDENT_PHASES = ("triage", "contain", "preserve evidence", "root cause", "notify", "corrective test or eval",
                   "safe reactivation")
AI_INCIDENTS = ("data disclosure", "unauthorised tool action", "stale retrieval", "injection bypass",
                "model regression", "runaway cost", "bias")


def runbook_problems(name: str, text: str, ai: bool = False) -> tuple[list[str], int]:
    """07/O16: every step (`### N. Title`) has a `**Verify:**` line; an exit code is read on its own line, right after
    the command, never through a pipe (`cmd | tail` reports tail's status, not the command's). Returns (problems, steps).
    """
    problems: list[str] = []
    lines = text.splitlines()
    steps: list[tuple[int, str, list[str]]] = []
    in_code, prev_cmd = False, ""
    for no, line in enumerate(lines, 1):
        if line.lstrip().startswith("```"):
            in_code, prev_cmd = not in_code, ""
            if steps:
                steps[-1][2].append(line)
            continue
        if not in_code:
            m = STEP.match(line)
            if m:
                steps.append((no, m.group(2), []))
                continue
            if line.startswith(("# ", "## ", "### ")) and steps:
                steps.append((no, "", []))  # a heading closes the step before it
                continue
        if steps:
            steps[-1][2].append(line)
        if not in_code:
            continue
        if PIPED_OUTPUT.search(line):
            problems.append(f"{name}:{no}: output piped into tail/head hides the command's exit code (07/O16)")
        if "$?" in line:
            if not EXIT_READ.match(line):
                problems.append(f'{name}:{no}: read an exit code on its own line (`echo "exit=$?"`), not inside '
                                "another command (07/O16)")
            elif "|" in prev_cmd:
                problems.append(f"{name}:{no}: this exit code is the last command of a pipe, not the step's (07/O16)")
        if line.strip() and not line.lstrip().startswith("#"):
            prev_cmd = line
    real = [s for s in steps if s[1]]
    for no, title, body in real:
        if not any(b.startswith("**Verify:**") for b in body):
            problems.append(f"{name}:{no}: step '{title}' has no **Verify:** line (07/O16)")
    if not real:
        problems.append(f"{name}: no numbered steps (`### 1. ...`), so nothing in it can be verified (07/O16)")
    if name.endswith("incident.md"):
        low = text.lower()
        titles = " ".join(t.lower() for _, t, _ in real)
        problems += [f"{name}: no step for '{p}' (07/O17)" for p in INCIDENT_PHASES if p not in titles]
        if "failure-log" not in low:
            problems.append(f"{name}: an incident must end in a failure-log hardening (07/O17, 10/H17)")
        if ai:
            problems += [f"{name}: the AI incident '{k}' is not covered (07/O17)" for k in AI_INCIDENTS if k not in low]
    return problems, len(real)


def make_targets() -> set[str]:
    mk = ROOT / "Makefile"
    return set(re.findall(r"^([a-z][a-z0-9-]*):", mk.read_text(), re.M)) if mk.is_file() else set()


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] == "--rule":
        _, err = parse_rule_header((ROOT / argv[2]).read_text())
        if err:
            print(err)
            return 1
        return 0

    fails: list[str] = []
    seen: dict[str, int] = {}
    rules_dir = ROOT / ".claude" / "rules"
    rules = sorted(rules_dir.glob("*.md"))
    all_globs: list[str] = []

    # H1: budgets
    claude = ROOT / "CLAUDE.md"
    ctext = claude.read_text()
    if len(ctext.splitlines()) > CLAUDE_MAX_LINES or len(ctext.encode()) > CLAUDE_MAX_BYTES:
        fails.append(f"CLAUDE.md is {len(ctext.splitlines())} lines / {len(ctext.encode())} bytes "
                     f"(budget {CLAUDE_MAX_LINES} lines / {CLAUDE_MAX_BYTES} bytes, 10/H1)")
    always = len(ctext.encode())

    # H2, H4: rule headers and change contracts
    for r in rules:
        text = r.read_text()
        globs, err = parse_rule_header(text)
        if err:
            fails.append(f"{r.name}: {err}")
        if r.name in ALWAYS_LOADED:
            if globs is not None:
                fails.append(f"{r.name} must be always loaded (no paths: header)")
            always += len(text.encode())
        elif globs is None and not err:
            fails.append(f"{r.name} has no paths: header (only {', '.join(ALWAYS_LOADED)} load always)")
        all_globs += globs or []
        if "## Change contract" not in text or any(f"**{c}**" not in text for c in CONTRACT):
            fails.append(f"{r.name}: missing the change contract ({' · '.join(CONTRACT)}) (10/H4)")
    if always > ALWAYS_MAX_BYTES:
        fails.append(f"always-loaded set is {always} bytes (budget {ALWAYS_MAX_BYTES}, 10/H1)")
    seen["rules"] = len(rules)

    # N8: every existing source folder is covered by some rule's paths
    folders = [p for p in ["scripts", "ops", "docs", "ai", "evals", "tests", "infra"] if (ROOT / p).is_dir()]
    for parent in ("apps", "packages"):
        if (ROOT / parent).is_dir():
            folders += [f"{parent}/{d.name}" for d in (ROOT / parent).iterdir() if d.is_dir()]
    for f in folders:
        probes = [f"{f}/probe.py", f"{f}/probe.md", f"{f}/sub/probe.py", f"{f}/sub/probe.md", f"{f}/src/x/probe.py"]
        if not any(glob_match(p, g) for p in probes for g in all_globs):
            fails.append(f"folder {f}/ is not covered by any rule's paths: (12/N8)")
    seen["source folders"] = len(folders)

    # N5: an operator script named test_* would be collected and run as a test
    scripts = sorted((ROOT / "scripts").glob("*.py")) if (ROOT / "scripts").is_dir() else []
    fails += [f"scripts/{p.name}: operator scripts are never named test_* (12/N5)" for p in scripts if p.name.startswith("test_")]
    seen["operator scripts"] = len(scripts)

    # H5: references in CLAUDE.md, AGENTS.md, rules, skills, agents, the hooks README and the runbooks must exist
    runbooks = sorted((ROOT / "ops" / "runbooks").glob("*.md")) if (ROOT / "ops" / "runbooks").is_dir() else []
    sources = [claude, ROOT / "AGENTS.md", ROOT / ".claude" / "hooks" / "README.md", *rules,
               *sorted((ROOT / ".claude" / "skills").rglob("*.md")), *sorted((ROOT / ".claude" / "agents").glob("*.md")),
               *runbooks]
    targets = make_targets()
    # H13: a failing step inside a pipe (`pytest | tail`) must still fail the target
    makefile = (ROOT / "Makefile").read_text() if (ROOT / "Makefile").is_file() else ""
    shell = re.search(r"^SHELL\s*:?=\s*(.*)$", makefile, re.M)
    if not shell or "-e" not in shell.group(1).split() or "pipefail" not in shell.group(1):
        fails.append("Makefile: recipes must run with `SHELL := /bin/bash -e -o pipefail`, or a red step in a pipe "
                     "passes (10/H13)")
    skills = {d.name for d in (ROOT / ".claude" / "skills").iterdir() if d.is_dir()}
    refs = pending = runtime = 0
    for src in sources:
        if not src.is_file():
            fails.append(f"missing {src.relative_to(ROOT)}")
            continue
        text = src.read_text()
        name = src.relative_to(ROOT).as_posix()
        # A command in a code block, arguments and all (`make deploy ENV=staging DIGEST=...`), names a real target too
        for block in re.findall(r"^```[^\n]*\n(.*?)^```", text, re.M | re.S):
            for target in re.findall(r"^\s*make ([a-z][a-z0-9-]*)(?=\s|$)", block, re.M):
                refs += 1
                if target not in targets:
                    fails.append(f"{name}: `make {target}` is not a Makefile target")
        for tok in re.findall(r"`([^`\n]+)`", text):
            tok = tok.strip()
            m = re.fullmatch(r"make ([a-z][a-z0-9-]*)(?: [A-Z_]+=\S*)*", tok)
            if m:
                refs += 1
                if m.group(1) not in targets:
                    fails.append(f"{name}: `make {m.group(1)}` is not a Makefile target")
                continue
            m = re.fullmatch(r"/([a-z][a-z-]*)", tok)
            if m and m.group(1) in SKILL_VOCAB:
                refs += 1
                if m.group(1) not in skills:
                    fails.append(f"{name}: `/{m.group(1)}` names a skill this project doesn't have")
                continue
            if any(ch in tok for ch in "*<>{}| ") or "..." in tok:
                continue
            if not (tok.startswith(REF_ROOTS) or tok in REF_FILES):
                continue
            refs += 1
            path = tok.rstrip("/.,;:")
            if path.startswith(RUNTIME):
                runtime += 1
                continue
            if any(path == a or path.startswith(a + "/") for a in AREAS) and not any(
                    (ROOT / a).is_dir() for a in AREAS if path == a or path.startswith(a + "/")):
                pending += 1
                continue
            if not (ROOT / path).exists():
                fails.append(f"{name}: references `{tok}`, which doesn't exist (10/H5)")
    seen["references"] = refs
    seen["references into areas not built yet"] = pending
    seen["references to runtime state"] = runtime

    # H9, H12: settings, deny rules and hook wiring
    try:
        settings = json.loads((ROOT / ".claude" / "settings.json").read_text())
    except (OSError, ValueError) as exc:
        fails.append(f".claude/settings.json is not valid JSON: {exc}")
        settings = {}
    missing = SECRET_DENIES - set(settings.get("permissions", {}).get("deny", []))
    if missing:
        fails.append(f"settings.json deny list lacks {sorted(missing)} (10/H9)")
    wired = set()
    for groups in settings.get("hooks", {}).values():
        for g in groups:
            for h in g.get("hooks", []):
                wired.update(re.findall(r"\.claude/hooks/([a-z_]+\.py)", h.get("command", "")))
    scripts = {p.name for p in (ROOT / ".claude" / "hooks").glob("*.py") if not p.name.startswith("_")}
    readme = (ROOT / ".claude" / "hooks" / "README.md").read_text()
    for s in sorted(scripts | wired):
        if s not in scripts:
            fails.append(f"settings.json wires {s}, which doesn't exist")
        elif s not in wired:
            fails.append(f"hook {s} exists but isn't wired in settings.json (10/H12)")
        if f"`{s}`" not in readme:
            fails.append(f"hook {s} is not documented in .claude/hooks/README.md (10/H12)")
    seen["hooks"] = len(scripts)

    # H22: MCP servers are an allowlist. `.mcp.json` lists them, each has a review row, and settings never approve
    # every project server at once nor one the allowlist doesn't hold. (Servers in a user's own settings can only be
    # blocked by managed settings; see .claude/reference/mcp-servers.md.)
    try:
        mcp = json.loads((ROOT / ".mcp.json").read_text()).get("mcpServers", {})
    except (OSError, ValueError) as exc:
        fails.append(f".mcp.json is not valid JSON: {exc}")
        mcp = {}
    if settings.get("enableAllProjectMcpServers") is not False:
        fails.append("settings.json must set enableAllProjectMcpServers to false: servers are approved one by one (10/H22)")
    for name in settings.get("enabledMcpjsonServers", []):
        if name not in mcp:
            fails.append(f"settings.json approves MCP server '{name}', which .mcp.json does not list (10/H22)")
    register = ROOT / ".claude" / "reference" / "mcp-servers.md"
    reviewed = register.read_text() if register.is_file() else ""
    for name in mcp:
        if f"| `{name}` |" not in reviewed:
            fails.append(
                f"MCP server '{name}' has no review row in .claude/reference/mcp-servers.md "
                "(owner, scopes, pinned version, tool descriptions read; 10/H22)"
            )
    seen["MCP servers allowlisted"] = len(mcp)

    # 01/R10, 12/N2: a compose service no code uses is a defect ("for later" infrastructure). Every service must be
    # named by the Makefile, a script, a workflow or the app code, outside compose.yaml itself.
    services = compose_services(ROOT / "compose.yaml")
    users = [ROOT / "Makefile", *(ROOT / "scripts").rglob("*"), *(ROOT / ".github").rglob("*"), *(ROOT / "apps").rglob("*")]
    corpus = "\n".join(
        p.read_text(errors="replace")
        for p in users
        if p.is_file() and not {"node_modules", ".venv", ".next", "dist"} & set(p.parts) and p.stat().st_size < 1_000_000
    )
    for name in services:
        if not re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", corpus):
            fails.append(f"compose service '{name}' is used by no Makefile target, script, workflow or app code (01/R10)")
    seen["compose services"] = len(services)

    # 07/O16, O17: runbooks (tiers S and E) are executable: every step verified, no exit code read through a pipe.
    runbooks = sorted(p for p in (ROOT / "ops" / "runbooks").glob("*.md") if p.name != "README.md")
    steps = 0
    for rb in runbooks:
        found, count = runbook_problems(rb.relative_to(ROOT).as_posix(), rb.read_text(), ai=(ROOT / "ai").is_dir())
        fails += found
        steps += count
    seen["runbooks"], seen["runbook steps"] = len(runbooks), steps

    # Skills and subagents
    skill_files = sorted((ROOT / ".claude" / "skills").glob("*/SKILL.md"))
    for sk in skill_files:
        text = sk.read_text()
        if not fm_fields(text).get("description"):
            fails.append(f"{sk.relative_to(ROOT)}: front-matter needs a description")
        if len(text.splitlines()) > 500:
            fails.append(f"{sk.relative_to(ROOT)}: over 500 lines; move detail to references/")
    seen["skills"] = len(skill_files)
    agents = sorted((ROOT / ".claude" / "agents").glob("*.md"))
    for ag in agents:
        f = fm_fields(ag.read_text())
        if not f.get("name") or not f.get("description"):
            fails.append(f"{ag.relative_to(ROOT)}: front-matter needs name and description")
        if ag.stem in ("spec-reviewer", "security-reviewer"):
            dis = f.get("disallowedTools", "")
            if "Edit" not in dis or "Write" not in dis:
                fails.append(f"{ag.relative_to(ROOT)}: a reviewer must disallow Edit and Write (10/H21)")
    seen["subagents"] = len(agents)
    seen["protected records checked in git history"] = history_check(fails)

    # A check that examined nothing must not pass (10/H18).
    for k in ("rules", "hooks", "skills", "references"):
        if seen.get(k, 0) == 0:
            fails.append(f"examined zero {k}: the check saw nothing, so it cannot pass")

    for k, v in seen.items():
        print(f"examined {v:4} {k}")
    if fails:
        print(f"\nharness-check FAIL: {len(fails)} problem(s)")
        for f in fails:
            print("  -", f)
        return 1
    print("harness-check: pass")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
