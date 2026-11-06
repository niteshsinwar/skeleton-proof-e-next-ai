"""Harness script tests (10/H12, H13, H18): every check is shown to pass on the real project AND to fail
on a planted fault, so no gate here is one that cannot fail.

Each test copies the project's harness into a temporary directory, plants one fault, and runs the script.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[3]
COPY = [".claude", "scripts", "docs", "ops", "CLAUDE.md", "AGENTS.md", "Makefile", ".mcp.json", "compose.yaml", ".github"]


class ScriptCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="harness-"))
        for item in COPY:
            src = PROJECT / item
            if src.is_dir():
                shutil.copytree(src, self.tmp / item, ignore=shutil.ignore_patterns("state", "__pycache__"))
            elif src.is_file():
                shutil.copy2(src, self.tmp / item)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_script(self, *args: str, env: dict | None = None, stdin: str | None = None) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-I", *args], cwd=self.tmp, capture_output=True, text=True,
                              env={**os.environ, **(env or {})}, input=stdin, timeout=120)

    def check(self) -> subprocess.CompletedProcess:
        return self.run_script("scripts/harness_check.py")

    def git(self, *args: str) -> None:
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.hooksPath=/dev/null", *args],
                       cwd=self.tmp, check=True, capture_output=True)


class HarnessCheck(ScriptCase):
    def test_passes_on_the_real_harness(self):
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("examined", r.stdout)

    def test_fails_when_claude_md_exceeds_its_budget(self):
        with open(self.tmp / "CLAUDE.md", "a") as f:
            f.write("\n".join(f"padding line {i}" for i in range(130)))
        self.assertIn("CLAUDE.md is", self.check().stdout)

    def test_fails_on_a_broken_rule_header(self):
        (self.tmp / ".claude" / "rules" / "docs.md").write_text("---\npaths: docs/**\n---\n# Docs\n")
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("docs.md", r.stdout)

    def test_fails_when_a_rule_references_a_missing_file(self):
        rule = self.tmp / ".claude" / "rules" / "docs.md"
        rule.write_text(rule.read_text() + "\nSee `docs/does-not-exist.md`.\n")
        self.assertIn("does-not-exist.md", self.check().stdout)

    def _mutation_project(self, test_catches: bool, find: str = "return 1") -> subprocess.CompletedProcess:
        """A tiny module, a fake test runner that fails only when the module is mutated, and one mutation."""
        (self.tmp / "apps" / "api").mkdir(parents=True, exist_ok=True)
        (self.tmp / "guard.py").write_text("def limit():\n    return 1\n")
        runner = self.tmp / "runner.py"
        flagged = "return 2" if test_catches else "never"
        runner.write_text(
            "import pathlib, sys\n"
            f"body = pathlib.Path({str(self.tmp / 'guard.py')!r}).read_text()\n"
            f"sys.exit(print('expected failure: limit changed') or 1) if {flagged!r} in body else sys.exit(0)\n"
        )
        (self.tmp / "m.toml").write_text(
            "[[mutation]]\n"
            f'name = "limit"\nfile = "guard.py"\nfind = "{find}"\nreplace = "return 2"\n'
            'test = "t"\nexpect = "limit changed"\n'
        )
        return self.run_script(
            "scripts/mutation_check.py", "--list", str(self.tmp / "m.toml"),
            env={"MUTATION_RUNNER": f"{sys.executable} -I {runner}"},
        )  # fmt: skip

    def test_a_mutation_that_the_test_catches_passes_and_the_file_is_restored(self):
        r = self._mutation_project(test_catches=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("examined 1 faults: 1 caught", r.stdout)
        self.assertEqual((self.tmp / "guard.py").read_text(), "def limit():\n    return 1\n")

    def test_a_mutation_that_survives_fails_the_run(self):
        r = self._mutation_project(test_catches=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("survived", r.stdout)
        self.assertEqual((self.tmp / "guard.py").read_text(), "def limit():\n    return 1\n")

    def test_a_stale_mutation_fails_the_run(self):
        r = self._mutation_project(test_catches=True, find="return 999")
        self.assertEqual(r.returncode, 1)
        self.assertIn("stale", r.stdout)

    def test_fails_when_an_operator_script_is_named_like_a_test(self):
        (self.tmp / "scripts" / "test_cleanup.py").write_text("print('would run as a test')\n")
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("scripts/test_cleanup.py", r.stdout)

    def test_fails_when_a_compose_service_is_used_by_nothing(self):
        # ResolveOS shipped Redis, Qdrant and Neo4j in compose with no code using them (01/R10).
        compose = self.tmp / "compose.yaml"
        compose.write_text(compose.read_text().replace("services:\n", "services:\n  redis:\n    image: redis:8\n", 1))
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("compose service 'redis' is used by no", r.stdout)
        self.assertIn("compose services", r.stdout)

    def test_fails_when_a_source_folder_has_no_rule(self):
        (self.tmp / "apps" / "mobile").mkdir(parents=True)  # a new app nobody wrote a rule for (12/N8)
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("folder apps/mobile/ is not covered", r.stdout)

    def test_fails_when_make_could_hide_a_red_step_in_a_pipe(self):
        mk = self.tmp / "Makefile"
        mk.write_text(mk.read_text().replace("SHELL := /bin/bash -e -o pipefail\n", "SHELL := /bin/bash\n"))
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("pipefail", r.stdout)

    def test_the_shell_flags_really_fail_a_pipe_with_a_red_step(self):
        header = "".join(l for l in (PROJECT / "Makefile").read_text().splitlines(True) if l.startswith("SHELL"))
        self.assertIn("pipefail", header)
        (self.tmp / "pipe.mk").write_text(header + "red:\n\t@false | cat\n")
        (self.tmp / "loose.mk").write_text("red:\n\t@false | cat\n")
        strict = subprocess.run(["make", "-s", "-f", "pipe.mk", "red"], cwd=self.tmp, capture_output=True)
        loose = subprocess.run(["make", "-s", "-f", "loose.mk", "red"], cwd=self.tmp, capture_output=True)
        self.assertNotEqual(strict.returncode, 0)  # the red step fails the target
        self.assertEqual(loose.returncode, 0)  # what would have happened without the flags

    def test_fails_when_a_make_target_or_skill_is_missing(self):
        claude = self.tmp / "CLAUDE.md"
        claude.write_text(claude.read_text() + "\nRun `make deploy-everything` then `/release`.\n")
        shutil.rmtree(self.tmp / ".claude" / "skills" / "release")
        out = self.check().stdout
        self.assertIn("make deploy-everything", out)
        self.assertIn("/release", out)

    def test_fails_when_a_hook_is_not_wired(self):
        settings = self.tmp / ".claude" / "settings.json"
        data = json.loads(settings.read_text())
        del data["hooks"]["Stop"]
        settings.write_text(json.dumps(data))
        self.assertIn("stop_gate.py exists but isn't wired", self.check().stdout)

    def test_fails_when_secret_deny_rules_are_missing(self):
        settings = self.tmp / ".claude" / "settings.json"
        data = json.loads(settings.read_text())
        data["permissions"]["deny"] = [d for d in data["permissions"]["deny"] if d != "Read(.env)"]
        settings.write_text(json.dumps(data))
        self.assertIn("deny list lacks", self.check().stdout)

    def test_mcp_servers_need_a_review_row_and_no_blanket_approval(self):
        mcp = self.tmp / ".mcp.json"
        mcp.write_text(json.dumps({"mcpServers": {"tracker": {"command": "npx", "args": ["tracker-mcp@1.2.3"]}}}))
        self.assertIn("MCP server 'tracker' has no review row", self.check().stdout)
        register = self.tmp / ".claude" / "reference" / "mcp-servers.md"
        register.write_text(register.read_text().replace("|---|---|---|---|---|\n",
            "|---|---|---|---|---|\n| `tracker` | Nitesh | read issues | 1.2.3 | 2026-11-04 |\n"))
        self.assertNotIn("has no review row", self.check().stdout)
        settings = self.tmp / ".claude" / "settings.json"
        data = json.loads(settings.read_text())
        data["enableAllProjectMcpServers"] = True
        data["enabledMcpjsonServers"] = ["unlisted"]
        settings.write_text(json.dumps(data))
        out = self.check().stdout
        self.assertIn("enableAllProjectMcpServers to false", out)
        self.assertIn("approves MCP server 'unlisted'", out)

    def test_fails_when_it_examined_nothing(self):
        for rule in (self.tmp / ".claude" / "rules").glob("*.md"):
            rule.unlink()
        self.assertIn("examined zero rules", self.check().stdout)

    def test_history_catches_an_accepted_adr_rewritten_behind_the_hook(self):
        adr = self.tmp / "docs" / "decisions" / "0002-store.md"
        adr.write_text("# ADR-0002\n\n**Status:** Accepted\n\n## Decision\n\nUse Postgres.\n")
        self.git("init", "-q", "-b", "main")
        self.git("add", "docs/decisions/0002-store.md", "ops/failure-log.md")
        self.git("commit", "-q", "-m", "docs: accept ADR-0002")
        self.assertEqual(self.check().returncode, 0, self.check().stdout)
        adr.write_text(adr.read_text().replace("Use Postgres.", "Use MySQL."))
        self.assertIn("accepted in", self.check().stdout)
        adr.write_text(adr.read_text().replace("Use MySQL.", "Use Postgres.").replace(
            "**Status:** Accepted", "**Status:** Superseded by ADR-0003"))
        self.assertEqual(self.check().returncode, 0, self.check().stdout)

    def test_history_catches_a_rewritten_failure_log(self):
        log = self.tmp / "ops" / "failure-log.md"
        log.write_text(log.read_text() + "\n## F-001 first\n- detail\n")
        self.git("init", "-q", "-b", "main")
        self.git("add", "ops/failure-log.md")
        self.git("commit", "-q", "-m", "docs: log F-001")
        log.write_text(log.read_text() + "\n## F-002 second\n")
        self.assertEqual(self.check().returncode, 0, self.check().stdout)
        log.write_text(log.read_text().replace("- detail", "- rewritten"))
        self.assertIn("append-only", self.check().stdout)


class RunbookLint(ScriptCase):
    """07/O16, O17: a runbook is executable. Each check is shown passing on a good runbook and failing on one fault."""

    GOOD = (
        "# Deploy\n\n### 1. Deploy the digest\n\n```bash\nmake deploy ENV=staging DIGEST=sha256:abc\n"
        'echo "exit=$?"\n```\n\n**Verify:** `exit=0` is printed.\n\n### 2. Smoke\n\nRun the smoke lane.\n\n'
        "**Verify:** it passes.\n"
    )

    def lint(self, text: str, name: str = "deploy.md") -> subprocess.CompletedProcess:
        folder = self.tmp / "ops" / "runbooks"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(text)
        return self.check()

    def test_a_runbook_with_verified_steps_passes(self):
        r = self.lint(self.GOOD)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertRegex(r.stdout, r"examined\s+[1-9]\d* runbook steps")

    def test_a_make_command_naming_no_target_fails(self):
        # 10/H5 over runbooks: a command with arguments in a code block names a real target (the GOOD one passes above)
        r = self.lint(self.GOOD.replace("make deploy ENV=staging", "make deplyo ENV=staging"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("ops/runbooks/deploy.md: `make deplyo` is not a Makefile target", r.stdout)

    def test_a_step_without_a_verify_line_fails(self):
        r = self.lint(self.GOOD.replace("**Verify:** it passes.\n", "It should pass.\n"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("ops/runbooks/deploy.md:12: step 'Smoke' has no **Verify:** line", r.stdout)

    def test_output_piped_into_tail_fails(self):
        r = self.lint(self.GOOD.replace("DIGEST=sha256:abc\n", "DIGEST=sha256:abc | tail -5\n"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("deploy.md:6: output piped into tail/head", r.stdout)

    def test_an_exit_code_read_after_a_pipe_fails(self):
        r = self.lint(self.GOOD.replace("DIGEST=sha256:abc\n", "DIGEST=sha256:abc | tee deploy.log\n"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("deploy.md:7: this exit code is the last command of a pipe", r.stdout)

    def test_an_exit_code_read_inside_another_command_fails(self):
        r = self.lint(self.GOOD.replace('DIGEST=sha256:abc\necho "exit=$?"\n', "DIGEST=sha256:abc; echo $?\n"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("deploy.md:6: read an exit code on its own line", r.stdout)

    def test_a_runbook_without_steps_fails(self):
        r = self.lint("# Deploy\n\nJust deploy it.\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("deploy.md: no numbered steps", r.stdout)

    def incident(self, drop: str = "") -> str:
        phases = ["Triage", "Contain", "Preserve evidence", "Root cause", "Notify", "Corrective test or eval",
                  "Safe reactivation"]
        steps = "".join(f"### {i}. {p}\n\nDo it.\n\n**Verify:** done.\n\n" for i, p in enumerate(phases, 1) if p != drop)
        kinds = "Data disclosure, unauthorised tool action, stale retrieval, injection bypass, model regression, " \
                "runaway cost, bias.\n"
        return f"# Incident\n\n{kinds}\n{steps}Close with an entry in ops/failure-log.md.\n"

    def test_an_incident_runbook_needs_every_response_phase(self):
        self.assertEqual(self.lint(self.incident(), "incident.md").returncode, 0)
        r = self.lint(self.incident(drop="Preserve evidence"), "incident.md")
        self.assertEqual(r.returncode, 1)
        self.assertIn("incident.md: no step for 'preserve evidence' (07/O17)", r.stdout)

    def test_an_ai_product_s_incident_runbook_covers_every_ai_incident(self):
        # Called directly: the full check reads "has AI" from the ai/ folder, which a non-AI project has no rule for.
        spec = importlib.util.spec_from_file_location("harness_check", self.tmp / "scripts" / "harness_check.py")
        hc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hc)
        self.assertEqual(hc.runbook_problems("incident.md", self.incident(), ai=True), ([], 7))
        found, _ = hc.runbook_problems("incident.md", self.incident().replace("injection bypass, ", ""), ai=True)
        self.assertEqual(found, ["incident.md: the AI incident 'injection bypass' is not covered (07/O17)"])
        self.assertEqual(hc.runbook_problems("incident.md", self.incident().replace("injection bypass, ", ""))[0], [])


class ReferenceFreshness(ScriptCase):
    """10/H17: notes about tools are re-verified within 21 days. Dates are injected, never today's (06/T10)."""

    def notes(self, **files: str) -> Path:
        folder = self.tmp / "notes"
        folder.mkdir(exist_ok=True)
        for name, text in files.items():
            (folder / f"{name}.md").write_text(text)
        (folder / "README.md").write_text("# Index, never dated\n")
        return folder

    def fresh(self, folder: Path, today: str) -> subprocess.CompletedProcess:
        return self.run_script("scripts/reference_freshness.py", "--dir", str(folder), "--today", today)

    def test_a_note_verified_21_days_ago_passes_and_22_fails(self):
        folder = self.notes(sdk="# SDK (verified 2026-01-01)\n\nFacts. Verified 2025-12-01 earlier.\n")
        ok = self.fresh(folder, "2026-01-22")
        self.assertEqual(ok.returncode, 0, ok.stdout)
        self.assertIn("examined 1 notes as of 2026-01-22", ok.stdout)
        stale = self.fresh(folder, "2026-01-23")
        self.assertEqual(stale.returncode, 1, stale.stdout)
        self.assertIn("sdk.md: verified 2026-01-01, 22 days ago (limit 21, 10/H17)", stale.stdout)

    def test_an_undated_note_fails(self):
        folder = self.notes(sdk="# SDK (verified 2026-01-01)\n", tool="# A tool\n\nNo date anywhere.\n")
        r = self.fresh(folder, "2026-01-02")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("tool.md: no `verified YYYY-MM-DD` date", r.stdout)
        self.assertNotIn("sdk.md", r.stdout)

    def test_a_folder_without_notes_fails(self):
        r = self.fresh(self.notes(), "2026-01-02")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no reference notes examined", r.stdout)

    def test_the_real_notes_are_all_dated(self):
        r = self.fresh(self.tmp / ".claude" / "reference", "2000-01-01")  # before any date: only undated notes fail
        self.assertNotIn("no `verified", r.stdout)
        self.assertRegex(r.stdout, r"examined [1-9]\d* notes")


class LinkCheck(ScriptCase):
    """Every relative Markdown link leads to a file and heading that exist; external links are never fetched."""

    def links(self, text: str) -> subprocess.CompletedProcess:
        root = self.tmp / "site"
        (root / "docs").mkdir(parents=True, exist_ok=True)
        (root / "docs" / "guide.md").write_text("# Guide\n\n## Getting started\n\n```\n# not a heading\n```\n")
        (root / "README.md").write_text(text)
        return self.run_script("scripts/link_check.py", "--root", str(root))

    GOOD = "See [the guide](docs/guide.md#getting-started), [home](https://example.com) and `[x](missing.md)`.\n"

    def test_working_links_pass_and_are_counted(self):
        r = self.links(self.GOOD)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("examined 2 Markdown files, 1 relative links", r.stdout)

    def test_a_link_to_a_missing_file_fails(self):
        r = self.links(self.GOOD.replace("docs/guide.md#", "docs/gide.md#"))
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("README.md:1: [docs/gide.md#getting-started] leads to a file that doesn't exist", r.stdout)

    def test_a_link_to_a_missing_heading_fails(self):
        r = self.links(self.GOOD.replace("#getting-started", "#not-a-heading"))
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("names a heading #not-a-heading that guide.md doesn't have", r.stdout)


class CommitGuard(ScriptCase):
    def stage(self, n: int, areas: int = 1) -> None:
        self.git("init", "-q", "-b", "main")
        for i in range(n):
            p = self.tmp / f"area{i % areas}" / f"f{i}.txt"
            p.parent.mkdir(exist_ok=True)
            p.write_text(str(i))
        self.git("add", *[f"area{i % areas}/f{i}.txt" for i in range(n)])

    def test_small_commit_passes(self):
        self.stage(3)
        self.assertEqual(self.run_script("scripts/commit_guard.py", env={"HARNESS_TIER": "S"}).returncode, 0)

    def test_bulk_commit_is_refused(self):
        self.stage(13)
        r = self.run_script("scripts/commit_guard.py", env={"HARNESS_TIER": "S"})
        self.assertEqual(r.returncode, 1, r.stdout)

    def test_too_many_areas_is_refused(self):
        self.stage(4, areas=4)
        self.assertEqual(self.run_script("scripts/commit_guard.py", env={"HARNESS_TIER": "E"}).returncode, 1)

    def test_override_with_a_reason_and_tier_p_are_allowed(self):
        self.stage(13)
        r = self.run_script("scripts/commit_guard.py", env={"HARNESS_TIER": "S", "COMMIT_GUARD_REASON": "vendored fixtures"})
        self.assertEqual(r.returncode, 0)
        self.assertIn("vendored fixtures", r.stdout)
        self.assertEqual(self.run_script("scripts/commit_guard.py", env={"HARNESS_TIER": "P"}).returncode, 0)


class CommitMessage(ScriptCase):
    def msg(self, text: str, tier: str = "S") -> int:
        f = self.tmp / "MSG"
        f.write_text(text)
        return self.run_script("scripts/commit_msg_check.py", str(f), env={"HARNESS_TIER": tier}).returncode

    def test_conventional_header_with_body_passes(self):
        self.assertEqual(self.msg("feat(api): add order submit\n\nCustomers need to submit orders.\n"), 0)
        self.assertEqual(self.msg("docs: fix a typo\n"), 0)

    def test_bad_header_or_missing_why_is_refused(self):
        self.assertEqual(self.msg("added stuff\n"), 1)
        self.assertEqual(self.msg("feat: add order submit\n"), 1)
        self.assertEqual(self.msg("feat: " + "x" * 80 + "\n\nwhy\n"), 1)

    def test_tier_p_and_git_generated_messages_pass(self):
        self.assertEqual(self.msg("feat: add order submit\n", tier="P"), 0)
        self.assertEqual(self.msg("Merge branch 'main' into x\n"), 0)


class Status(ScriptCase):
    def test_status_counts_from_the_repo(self):
        r = self.run_script("scripts/status.py")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"Workflow skills\s+\d+")
        self.assertNotRegex(r.stdout, r"\d+%")


class WorkflowCheck(ScriptCase):
    """scripts/workflow_check.py: the CI workflow can't be quietly weakened (13/V5, 11/GL3), tested both ways."""

    def ci(self) -> Path:
        return self.tmp / ".github" / "workflows" / "ci.yml"

    def run_check(self) -> subprocess.CompletedProcess:
        return self.run_script("scripts/workflow_check.py")

    def test_passes_on_the_real_workflow(self):
        r = self.run_check()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertRegex(r.stdout, r"examined 3 workflows, [1-9][0-9]* third-party actions")

    def test_a_mutable_tag_is_refused(self):
        # trivy-action, 2026: tags were force-pushed; only a full commit SHA is immutable.
        text = self.ci().read_text()
        self.ci().write_text(text.replace("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", "actions/checkout@v7", 1))
        r = self.run_check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("`actions/checkout@v7` is not pinned to a full commit SHA", r.stdout)

    def test_pull_request_target_is_refused(self):
        self.ci().write_text(self.ci().read_text().replace("  pull_request:\n", "  pull_request_target:\n", 1))
        r = self.run_check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("pull_request_target", r.stdout)

    def test_a_job_outside_the_gate_is_refused(self):
        text = self.ci().read_text()
        self.assertIn(", security, images", text)  # the fault below is really planted, at every tier
        self.ci().write_text(text.replace(", security, images", ", images", 1))
        r = self.run_check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("the gate does not need ['security']", r.stdout)

    def test_the_nightly_workflow_is_held_to_the_same_pins_and_token(self):
        nightly = self.tmp / ".github" / "workflows" / "nightly.yml"
        text = nightly.read_text()
        self.assertEqual(self.run_check().returncode, 0)
        nightly.write_text(text.replace("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", "actions/checkout@v7", 1))
        r = self.run_check()
        self.assertEqual(r.returncode, 1)
        self.assertIn(".github/workflows/nightly.yml: `actions/checkout@v7` is not pinned", r.stdout)
        nightly.write_text(text.replace("permissions:\n  contents: read\n", "permissions: write-all\n", 1))
        r = self.run_check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("nightly.yml: the top-level token must be read-only", r.stdout)

    def test_a_missing_merge_group_trigger_is_refused(self):
        self.ci().write_text(self.ci().read_text().replace("  merge_group:\n", "", 1))
        r = self.run_check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("no merge_group trigger", r.stdout)


class CiChanges(ScriptCase):
    """scripts/ci_changes.py fails closed: only a documentation-only pull request skips the build jobs."""

    def setUp(self) -> None:
        super().setUp()
        self.git("init", "-q", "-b", "main")
        (self.tmp / "apps").mkdir(exist_ok=True)
        (self.tmp / "apps" / "app.py").write_text("x = 1\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.tmp, capture_output=True, text=True).stdout.strip()

    def classify(self, event: str = "pull_request") -> str:
        r = self.run_script("scripts/ci_changes.py", "--event", event, "--base", self.base)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def commit(self, path: str, text: str) -> None:
        (self.tmp / path).parent.mkdir(parents=True, exist_ok=True)
        (self.tmp / path).write_text(text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "change")

    def test_a_docs_only_pull_request_skips_the_build_jobs(self):
        self.commit("docs/guide.md", "words\n")
        self.assertEqual(self.classify(), "code=false")

    def test_a_code_change_runs_everything(self):
        self.commit("docs/guide.md", "words\n")
        self.commit("apps/app.py", "x = 2\n")
        self.assertEqual(self.classify(), "code=true")

    def test_a_rule_or_skill_change_is_never_documentation_only(self):
        self.commit(".claude/rules/new.md", "a rule steers the agent\n")
        self.assertEqual(self.classify(), "code=true")

    def test_a_push_or_an_unknown_base_runs_everything(self):
        self.commit("docs/guide.md", "words\n")
        self.assertEqual(self.classify(event="push"), "code=true")
        r = self.run_script("scripts/ci_changes.py", "--event", "pull_request", "--base", "0" * 40)
        self.assertEqual(r.stdout.strip(), "code=true", "a base git can't resolve fails closed")


class Tools(ScriptCase):
    """scripts/tools.py never installs a download it can't verify (13/V3)."""

    def manifest(self, sha: str | None) -> None:
        payload = self.tmp / "payload-tool"
        payload.write_text("#!/bin/sh\necho tool\n")
        import hashlib, platform as plat  # noqa: E401  (test-local)
        system, machine = plat.system().lower(), plat.machine().lower()
        key = f"{system}-{ {'arm64': 'arm64', 'aarch64': 'arm64', 'x86_64': 'x64', 'amd64': 'x64'}.get(machine, machine)}"
        good = hashlib.sha256(payload.read_bytes()).hexdigest()
        line = f'sha256 = {{ {key} = "{sha if sha is not None else good}" }}' if sha != "" else "sha256 = {}"
        (self.tmp / "ops" / "tools.toml").write_text(
            f'[binary.payload-tool]\nversion = "1.0.0"\nurl = "file://{payload}"\n'
            f'platforms = {{ {key} = "x" }}\n{line}\n'
        )

    def test_a_verified_download_installs_and_check_then_passes(self):
        self.manifest(sha=None)
        r = self.run_script("scripts/tools.py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("installed payload-tool 1.0.0 (sha256 verified)", r.stdout)
        self.assertEqual(self.run_script("scripts/tools.py", "--check").returncode, 0)

    def test_a_checksum_mismatch_is_refused_and_nothing_is_installed(self):
        self.manifest(sha="0" * 64)
        r = self.run_script("scripts/tools.py")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("checksum mismatch", r.stdout + r.stderr)
        self.assertFalse((self.tmp / ".tools" / "bin" / "payload-tool").exists())

    def test_a_missing_checksum_is_refused(self):
        self.manifest(sha="")
        r = self.run_script("scripts/tools.py")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no sha256", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
