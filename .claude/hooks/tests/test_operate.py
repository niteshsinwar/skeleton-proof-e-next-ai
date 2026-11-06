"""Operate (tiers S and E): SLOs and their burn-rate alerts (07/O13-O15), each rule tested both ways.

The maths is checked against values worked out by hand from the SRE Workbook's policy, never against the code's own
output; each refusal is paired with the same file passing once the fault is removed.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[3]
SCRIPT = PROJECT / "scripts" / "slo.py"


def _module():
    spec = importlib.util.spec_from_file_location("slo", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["slo"] = mod  # dataclasses look their module up while the class is built
    spec.loader.exec_module(mod)
    return mod


slo = _module()

RUNBOOK = "# Incident\n\n### 1. Triage\n\nLook.\n\n**Verify:** looked.\n\n## AI incidents\n\nTable.\n"
JOURNEY = """# a comment line
journey: orders
title: Orders
starter: true
window_days: 30
routes:
  - GET /orders
  - POST /orders/{order_id}/pay  # a trailing comment
objectives:
  availability:
    target: 99.5
    owner: "@payments-oncall"
    runbook: ops/runbooks/incident.md#1-triage
  latency:
    target: 95
    threshold_ms: 500
    owner: "@payments-oncall"
    runbook: ops/runbooks/incident.md
  quality:
    target: 95
    step: order_summary
    owner: "@ai-quality"
    runbook: ops/runbooks/incident.md#ai-incidents
"""


class BurnRateMaths(unittest.TestCase):
    """07/O14, W37: page at 2% of the budget in 1 h or 5% in 6 h; ticket at 10% in 3 days; short window = long / 12."""

    def test_the_error_budget(self):
        self.assertEqual(slo.budget(99.5), 0.005)
        self.assertEqual(slo.budget(99.9), 0.001)
        self.assertEqual(slo.budget(95), 0.05)

    def test_burn_rates_for_a_30_day_window(self):
        # 2% of 720 h spent in 1 h = 14.4x; 5% in 6 h = 6x; 10% in 72 h = 1x.
        self.assertEqual([r[1] for r in slo.burn_thresholds(99.5, 30)], [14.4, 6.0, 1.0])

    def test_burn_rates_for_a_28_day_window(self):
        rates = [r[1] for r in slo.burn_thresholds(99.5, 28)]
        self.assertEqual(rates[:2], [13.44, 5.6])
        self.assertAlmostEqual(rates[2], 0.9333333333, places=9)

    def test_thresholds_are_burn_rate_times_budget(self):
        self.assertEqual([r[4] for r in slo.burn_thresholds(99.5, 30)], [0.072, 0.03, 0.005])
        self.assertEqual([r[4] for r in slo.burn_thresholds(99.9, 30)], [0.0144, 0.006, 0.001])

    def test_windows_and_severities(self):
        rows = slo.burn_thresholds(99.5, 30)
        self.assertEqual([(r[0], slo.duration(r[2]), slo.duration(r[3])) for r in rows],
                         [("page", "1h", "5m"), ("page", "6h", "30m"), ("ticket", "3d", "6h")])

    def test_a_page_at_14_4x_spends_2_percent_of_the_budget_in_an_hour(self):
        budget_hours = 30 * 24 * slo.budget(99.5)  # 3.6 h of errors allowed in the window
        spent_in_one_hour = 0.072 * 1  # an error ratio of 0.072 for 1 h
        self.assertAlmostEqual(spent_in_one_hour / budget_hours, 0.02)


class SLOFiles(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="slo-"))
        (self.root / "ops" / "runbooks").mkdir(parents=True)
        (self.root / "ops" / "runbooks" / "incident.md").write_text(RUNBOOK)
        (self.root / "ops" / "slo").mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def run_slo(self, *args: str, text: str = JOURNEY, name: str = "orders") -> subprocess.CompletedProcess:
        (self.root / "ops" / "slo" / f"{name}.yaml").write_text(text)
        return subprocess.run(
            [sys.executable, "-I", str(SCRIPT), *args, "--dir", str(self.root / "ops" / "slo"), "--root", str(self.root)],
            capture_output=True, text=True, timeout=60, env=os.environ,
        )

    def assert_refused(self, fault: str, fixed: str, message: str) -> None:
        """The same file passes without the fault and fails with it, naming why."""
        good = self.run_slo("check", text=fixed)
        self.assertEqual(good.returncode, 0, good.stdout)
        bad = self.run_slo("check", text=fault)
        self.assertEqual(bad.returncode, 1, bad.stdout)
        self.assertIn(message, bad.stdout)

    def test_a_valid_journey_passes_and_counts_what_it_examined(self):
        r = self.run_slo("check")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("examined 1 journeys, 3 objectives, 1 still starters", r.stdout)

    def test_an_unknown_key_is_refused(self):
        self.assert_refused(JOURNEY.replace("    target: 99.5\n", "    target: 99.5\n    targett: 99\n"), JOURNEY,
                            "orders.yaml:12: unknown key 'targett'")

    def test_an_alert_without_an_owner_is_refused(self):
        self.assert_refused(JOURNEY.replace('    owner: "@ai-quality"\n', ""), JOURNEY, "missing owner")
        self.assert_refused(JOURNEY.replace('"@ai-quality"', '""'), JOURNEY, "every alert has an owner (07/O15)")

    def test_an_alert_without_a_runbook_is_refused(self):
        self.assert_refused(JOURNEY.replace("    runbook: ops/runbooks/incident.md\n", ""), JOURNEY, "missing runbook")
        self.assert_refused(JOURNEY.replace("incident.md#ai-incidents", "outage.md"), JOURNEY,
                            "runbook 'ops/runbooks/outage.md' is not a file under ops/runbooks/")

    def test_a_runbook_anchor_that_does_not_exist_is_refused(self):
        self.assert_refused(JOURNEY.replace("#1-triage", "#triage"), JOURNEY, "has no heading with the anchor #triage")

    def test_a_latency_threshold_off_the_histogram_buckets_is_refused(self):
        self.assert_refused(JOURNEY.replace("threshold_ms: 500", "threshold_ms: 400"), JOURNEY,
                            "threshold_ms must be a histogram bucket boundary")

    def test_a_target_too_low_for_its_page_to_ever_fire_is_refused(self):
        # At 90% the budget is 0.1, and the 1 h page needs an error ratio above 14.4 x 0.1 = 1.44: impossible.
        self.assert_refused(JOURNEY.replace("target: 95\n    step", "target: 90\n    step"), JOURNEY,
                            "at 90% the page over 1h alert needs an error ratio above 1, so it can never fire")

    def test_a_target_outside_0_to_100_is_refused(self):
        self.assert_refused(JOURNEY.replace("target: 99.5", "target: 100"), JOURNEY, "strictly between 0 and 100")

    def test_a_measured_slo_needs_its_date_and_a_starter_has_none(self):
        measured = JOURNEY.replace("starter: true", "starter: false\nmeasured: 2026-11-01")
        self.assert_refused(JOURNEY.replace("starter: true", "starter: false"), measured, "needs `measured: YYYY-MM-DD`")
        self.assert_refused(JOURNEY.replace("starter: true", "starter: true\nmeasured: 2026-11-01"), JOURNEY,
                            "a starter has no measured date")

    def test_availability_is_required_and_routes_are_method_and_path(self):
        no_availability = JOURNEY.replace("  availability:\n    target: 99.5\n", "  avail:\n    target: 99.5\n")
        self.assert_refused(no_availability, JOURNEY, "unknown key 'avail'")
        self.assert_refused(JOURNEY.replace("  - GET /orders\n", "  - /orders\n"), JOURNEY, "a route is 'METHOD /path'")

    def test_yaml_outside_the_strict_subset_is_refused(self):
        self.assert_refused(JOURNEY.replace("title: Orders", "title: &t Orders"), JOURNEY, "outside the subset")
        self.assert_refused(JOURNEY.replace('"@payments-oncall"', "@payments-oncall", 1), JOURNEY, "quote the value")
        self.assert_refused(JOURNEY.replace("title: Orders", "title: Orders\ntitle: Again"), JOURNEY, "duplicate key")
        self.assert_refused(JOURNEY.replace("  - GET /orders", "\t- GET /orders"), JOURNEY, "a tab")
        self.assert_refused(JOURNEY.replace("starter: true", "starter: yes"), JOURNEY, "ambiguous YAML")

    def test_a_folder_without_slo_files_is_refused(self):
        r = subprocess.run([sys.executable, "-I", str(SCRIPT), "check", "--dir", str(self.root / "ops" / "slo")],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 1)
        self.assertIn("no SLO files", r.stdout)

    def test_alerts_page_and_ticket_with_the_policy_thresholds(self):
        r = self.run_slo("alerts")
        self.assertEqual(r.returncode, 0, r.stderr)
        rules = r.stdout
        self.assertTrue(rules.startswith("# Generated by scripts/slo.py"), rules[:200])  # only rules on stdout
        for window in ("5m", "30m", "1h", "6h", "3d"):
            self.assertIn(f"record: slo:sli_error:ratio_rate{window}", rules)
        page = 'slo:sli_error:ratio_rate1h{journey=\\"orders\\",objective=\\"availability\\"} > 0.072 and ' \
               'slo:sli_error:ratio_rate5m{journey=\\"orders\\",objective=\\"availability\\"} > 0.072'
        self.assertIn(page, rules)
        self.assertIn('ratio_rate6h{journey=\\"orders\\",objective=\\"availability\\"} > 0.03 and', rules)
        self.assertIn('ratio_rate3d{journey=\\"orders\\",objective=\\"availability\\"} > 0.005 and', rules)
        self.assertIn('http_response_status_code=~\\"5..\\"', rules)
        self.assertIn('le=\\"0.5\\"', rules)

    def test_system_down_and_ai_quality_degraded_are_separate_alerts(self):
        rules = self.run_slo("alerts").stdout
        alerts = [line.split("alert: ")[1] for line in rules.splitlines() if "- alert: " in line]
        self.assertEqual(alerts, ["OrdersSystemDownPage", "OrdersSystemDownTicket", "OrdersSystemSlowPage",
                                  "OrdersSystemSlowTicket", "OrdersAIQualityDegradedPage",
                                  "OrdersAIQualityDegradedTicket"])
        quality = rules[rules.index("alert: OrdersAIQualityDegradedPage"):]
        self.assertIn("alert_class: ai-quality", quality)
        self.assertIn('owner: "@ai-quality"', quality)
        self.assertIn('runbook: "ops/runbooks/incident.md#ai-incidents"', quality)
        self.assertNotIn("http_server_request_duration", quality.split("- alert:")[1])
        down = rules[rules.index("alert: OrdersSystemDownPage"):rules.index("alert: OrdersSystemDownTicket")]
        self.assertIn("alert_class: system", down)
        self.assertNotIn("ai_quality", down)

    def test_an_unnamed_owner_blocks_the_alerts_but_not_the_check(self):
        placeholder = JOURNEY.replace('"@ai-quality"', '"@OWNER"')
        checked = self.run_slo("check", text=placeholder)
        self.assertEqual(checked.returncode, 0, checked.stdout)
        self.assertIn("OPEN  owner @OWNER for ops/slo/orders.yaml: quality", checked.stdout)
        refused = self.run_slo("alerts", text=placeholder)
        self.assertEqual(refused.returncode, 1)
        self.assertIn("1 alert(s) have no named owner", refused.stderr)
        self.assertEqual(refused.stdout, "")
        self.assertEqual(self.run_slo("alerts", "--allow-open-owners", text=placeholder).returncode, 0)
        self.assertEqual(self.run_slo("alerts").returncode, 0)


class ThisProjectsSLOs(unittest.TestCase):
    """The project's own files load, every alert has a runbook here, and only the unnamed owners block the alerts."""

    def run_real(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-I", str(SCRIPT), *args], capture_output=True, text=True, timeout=60)

    def test_the_project_slos_load(self):
        r = self.run_real("check")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertRegex(r.stdout, r"examined [1-9]\d* journeys")

    def test_the_project_alerts_wait_for_named_owners(self):
        refused = self.run_real("alerts")
        self.assertEqual(refused.returncode, 1, refused.stderr)
        self.assertIn("no named owner", refused.stderr)
        preview = self.run_real("alerts", "--allow-open-owners")
        self.assertEqual(preview.returncode, 0, preview.stdout)
        self.assertIn("SystemDownPage", preview.stdout)
        self.assertEqual("AIQualityDegradedPage" in preview.stdout, (PROJECT / "ai").is_dir())


if __name__ == "__main__":
    unittest.main()
