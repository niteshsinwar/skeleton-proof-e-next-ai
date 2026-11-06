"""Hook tests, both directions (10/H12): every guard is shown to block AND to allow.

Each test runs the real hook script as Claude Code would: JSON on stdin, CLAUDE_PROJECT_DIR set to a
temporary copy of the project's harness. Standard library only.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[3]
HOOKS = PROJECT / ".claude" / "hooks"


class HookCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="hooks-"))
        shutil.copytree(HOOKS, self.tmp / ".claude" / "hooks", ignore=shutil.ignore_patterns("tests", "__pycache__"))
        shutil.copytree(PROJECT / "scripts", self.tmp / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
        (self.tmp / "docs" / "decisions").mkdir(parents=True)
        (self.tmp / "ops").mkdir()
        (self.tmp / "docs" / "STATE.md").write_text("# STATE\n\nDated 2026-11-04. Nothing built yet.\n")
        (self.tmp / "ops" / "failure-log.md").write_text("# Failure log\n\n## F-001 first\n")
        (self.tmp / "docs" / "decisions" / "0002-accepted.md").write_text(
            "# ADR-0002\n\n**Status:** Accepted\n\n## Decision\n\nUse Postgres.\n")
        (self.tmp / "docs" / "decisions" / "0003-proposed.md").write_text(
            "# ADR-0003\n\n**Status:** Proposed\n\n## Decision\n\nMaybe Redis.\n")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_hook(self, name: str, payload, tier: str = "S", raw: str | None = None) -> tuple[int, str]:
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.tmp), "HARNESS_TIER": tier}
        data = raw if raw is not None else json.dumps(payload)
        r = subprocess.run([sys.executable, str(self.tmp / ".claude" / "hooks" / name)], input=data,
                           capture_output=True, text=True, env=env, cwd=self.tmp, timeout=120)
        return r.returncode, r.stdout

    def decision(self, payload, **kw) -> str:
        code, out = self.run_hook("protect.py", payload, **kw)
        self.assertEqual(code, 0, out)
        if not out.strip():
            return "allow"
        return json.loads(out)["hookSpecificOutput"]["permissionDecision"]

    def tool(self, name: str, agent: str | None = None, **tool_input) -> dict:
        p = {"session_id": "t", "hook_event_name": "PreToolUse", "tool_name": name, "tool_input": tool_input}
        if agent:
            p["agent_type"] = agent
        return p


class ProtectSecrets(HookCase):
    def test_env_file_is_denied(self):
        self.assertEqual(self.decision(self.tool("Read", file_path=str(self.tmp / ".env"))), "deny")

    def test_env_example_is_allowed(self):
        self.assertEqual(self.decision(self.tool("Read", file_path=".env.example")), "allow")

    def test_key_material_is_denied(self):
        self.assertEqual(self.decision(self.tool("Read", file_path="config/server.pem")), "deny")
        self.assertEqual(self.decision(self.tool("Write", file_path="secrets/token.txt", content="x")), "deny")

    def test_ordinary_file_is_allowed(self):
        self.assertEqual(self.decision(self.tool("Read", file_path="docs/STATE.md")), "allow")

    def test_bash_reading_a_secret_is_denied(self):
        self.assertEqual(self.decision(self.tool("Bash", command="cat .env")), "deny")
        self.assertEqual(self.decision(self.tool("Bash", command="cat .env.example")), "allow")

    def test_unreadable_payload_fails_closed(self):
        code, out = self.run_hook("protect.py", None, raw="not json")
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")


class ProtectCommands(HookCase):
    def test_destructive_git_is_denied(self):
        for cmd in ("git add -A", "git add .", "git push --force origin main", "git push -f",
                    "git reset --hard HEAD~1", "git clean -fd", "git commit --no-verify -m x", "git checkout -- ."):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.decision(self.tool("Bash", command=cmd)), "deny")

    def test_ordinary_git_is_allowed(self):
        for cmd in ("git add src/app.py docs/STATE.md", "git push origin main", "git status", "git commit -m 'fix: x'"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.decision(self.tool("Bash", command=cmd)), "allow")

    def test_rm_outside_project_is_denied_inside_is_allowed(self):
        self.assertEqual(self.decision(self.tool("Bash", command="rm -rf /")), "deny")
        self.assertEqual(self.decision(self.tool("Bash", command="rm -rf ../other")), "deny")
        self.assertEqual(self.decision(self.tool("Bash", command="rm -rf build")), "allow")

    def test_production_deploy_is_denied(self):
        self.assertEqual(self.decision(self.tool("Bash", command="make deploy ENV=production")), "deny")
        self.assertEqual(self.decision(self.tool("Bash", command="make deploy ENV=staging")), "allow")


class ProtectRecords(HookCase):
    ADR = "docs/decisions/0002-accepted.md"

    def test_accepted_adr_body_is_immutable(self):
        p = self.tool("Edit", file_path=self.ADR, old_string="Use Postgres.", new_string="Use MySQL.")
        self.assertEqual(self.decision(p), "deny")

    def test_accepted_adr_status_line_may_change(self):
        p = self.tool("Edit", file_path=self.ADR, old_string="**Status:** Accepted",
                      new_string="**Status:** Superseded by ADR-0004")
        self.assertEqual(self.decision(p), "allow")

    def test_proposed_adr_is_editable(self):
        p = self.tool("Edit", file_path="docs/decisions/0003-proposed.md", old_string="Maybe Redis.",
                      new_string="Use Redis.")
        self.assertEqual(self.decision(p), "allow")

    def test_shell_write_to_adr_is_denied_read_is_allowed(self):
        self.assertEqual(self.decision(self.tool("Bash", command=f"sed -i '' 's/a/b/' {self.ADR}")), "deny")
        self.assertEqual(self.decision(self.tool("Bash", command=f"cat {self.ADR} 2>&1")), "allow")

    def test_failure_log_is_append_only(self):
        old = "## F-001 first\n"
        self.assertEqual(self.decision(self.tool("Edit", file_path="ops/failure-log.md", old_string=old,
                                                 new_string=old + "\n## F-002 second\n")), "allow")
        self.assertEqual(self.decision(self.tool("Edit", file_path="ops/failure-log.md", old_string=old,
                                                 new_string="## F-001 rewritten\n")), "deny")
        self.assertEqual(self.decision(self.tool("Bash", command="echo '## F-002' >> ops/failure-log.md")), "allow")
        self.assertEqual(self.decision(self.tool("Bash", command="echo '' > ops/failure-log.md")), "deny")


class ProtectAgentScopes(HookCase):
    def test_test_author_cannot_read_source(self):
        self.assertEqual(self.decision(self.tool("Read", "test-author", file_path="apps/api/src/pkg/x.py")), "deny")
        self.assertEqual(self.decision(self.tool("Read", "test-author", file_path="docs/specs/a/spec.md")), "allow")

    def test_eval_author_cannot_edit_prompts(self):
        self.assertEqual(self.decision(self.tool("Edit", "eval-author", file_path="ai/agents/a/v1.yaml",
                                                 old_string="a", new_string="b")), "deny")
        self.assertEqual(self.decision(self.tool("Write", "eval-author", file_path="evals/datasets/a/v1/c.json",
                                                 content="{}")), "allow")

    def test_researcher_writes_only_reference(self):
        self.assertEqual(self.decision(self.tool("Write", "researcher", file_path="docs/x.md", content="x")), "deny")
        self.assertEqual(self.decision(self.tool("Write", "researcher", file_path=".claude/reference/x.md",
                                                 content="x")), "allow")

    def test_reviewers_are_read_only(self):
        self.assertEqual(self.decision(self.tool("Edit", "spec-reviewer", file_path="docs/STATE.md",
                                                 old_string="a", new_string="b")), "deny")
        self.assertEqual(self.decision(self.tool("Read", "security-reviewer", file_path="docs/STATE.md")), "allow")


class StopGate(HookCase):
    def make(self, ok: bool) -> None:
        (self.tmp / "Makefile").write_text(f"check:\n\t@echo checking\n\t@exit {0 if ok else 1}\n")

    def test_red_check_blocks_at_tier_s(self):
        self.make(False)
        code, out = self.run_hook("stop_gate.py", {"session_id": "t", "stop_hook_active": False}, tier="S")
        self.assertEqual(json.loads(out)["decision"], "block")

    def test_red_check_only_warns_at_tier_p(self):
        self.make(False)
        code, out = self.run_hook("stop_gate.py", {"session_id": "t", "stop_hook_active": False}, tier="P")
        self.assertNotIn("decision", json.loads(out))
        self.assertIn("systemMessage", json.loads(out))

    def test_green_check_lets_claude_stop(self):
        self.make(True)
        code, out = self.run_hook("stop_gate.py", {"session_id": "t", "stop_hook_active": False}, tier="E")
        self.assertEqual(out.strip(), "")

    def test_never_blocks_twice_in_a_row(self):
        self.make(False)
        code, out = self.run_hook("stop_gate.py", {"session_id": "t", "stop_hook_active": True}, tier="S")
        self.assertEqual(out.strip(), "")


class SessionLoop(HookCase):
    def test_session_start_injects_state(self):
        code, out = self.run_hook("session_start.py", {"session_id": "t", "source": "startup"})
        self.assertIn("Nothing built yet", out)
        self.assertIn("tier S", out)

    def test_breadcrumb_survives_compaction(self):
        self.run_hook("pre_compact.py", {"session_id": "t", "trigger": "auto"})
        code, out = self.run_hook("post_compact.py", {"session_id": "t", "source": "compact"})
        self.assertIn("Breadcrumb from before compaction", out)

    def test_compaction_without_breadcrumb_still_reminds(self):
        code, out = self.run_hook("post_compact.py", {"session_id": "none", "source": "compact"})
        self.assertIn("re-read docs/STATE.md", out)

    def test_drift_watch_is_silent_outside_git(self):
        code, out = self.run_hook("drift_watch.py", {"session_id": "t", "prompt": "hi"})
        self.assertEqual(out.strip(), "")

    def test_edits_and_failures_reach_the_operating_record(self):
        self.run_hook("post_edit.py", {"session_id": "t", "tool_name": "Edit",
                                       "tool_input": {"file_path": "docs/STATE.md"}})
        self.run_hook("tool_failure.py", {"session_id": "t", "tool_name": "Bash", "error": "exit 1"})
        self.run_hook("session_end.py", {"session_id": "t", "reason": "other"})
        record = (self.tmp / ".claude" / "state" / "sessions" / "t.md").read_text()
        self.assertIn("docs/STATE.md", record)
        self.assertIn("Tool failures: 1", record)

    def test_broken_rule_header_is_reported(self):
        rules = self.tmp / ".claude" / "rules"
        rules.mkdir(parents=True)
        (rules / "bad.md").write_text("---\npaths: [unclosed\n---\n# Bad\n")
        code, out = self.run_hook("post_edit.py", {"session_id": "t", "tool_name": "Write",
                                                   "tool_input": {"file_path": ".claude/rules/bad.md"}})
        self.assertEqual(json.loads(out)["decision"], "block")
        (rules / "good.md").write_text('---\npaths:\n  - "apps/**"\n---\n# Good\n')
        code, out = self.run_hook("post_edit.py", {"session_id": "t", "tool_name": "Write",
                                                   "tool_input": {"file_path": ".claude/rules/good.md"}})
        self.assertEqual(out.strip(), "")


if __name__ == "__main__":
    unittest.main()
