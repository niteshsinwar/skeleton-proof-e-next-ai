"""scripts/expiry_check.py: nothing lapses unnoticed (07/O18, O23), judged against an injected date (06/T10)."""

from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path
from types import ModuleType

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
TODAY = date(2026, 11, 6)


def expiry() -> ModuleType:
    spec = importlib.util.spec_from_file_location("expiry_check", ROOT / "scripts" / "expiry_check.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["expiry_check"] = module  # a dataclass resolves its module through sys.modules
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(("days", "level"), [(0, "fail"), (21, "fail"), (22, "warn"), (45, "warn"), (46, None)])
def test_a_certificate_fails_inside_its_window_and_warns_before_it(days: int, level: str | None) -> None:
    found = expiry().judge("certificate of x", days, 21, 45)
    assert (found.level if found else None) == level


def test_an_unreachable_host_is_a_failure_never_a_pass(capsys: pytest.CaptureFixture[str]) -> None:
    assert expiry().main(["--today", TODAY.isoformat(), "--hosts", "127.0.0.1:1"]) == 1
    assert "FAIL certificate of 127.0.0.1:1" in capsys.readouterr().out


def catalogue_retiring_in(tmp_path: Path, days: int) -> Path:
    data = yaml.safe_load((ROOT / "ai" / "models.yaml").read_text(encoding="utf-8"))
    model = data["routes"]["default"]["model"]
    data["models"][model]["retires_on"] = (TODAY + timedelta(days=days)).isoformat()
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


@pytest.mark.parametrize(("days", "level"), [(10, "fail"), (60, "warn"), (200, None)])
def test_a_model_retiring_soon_fails_and_one_retiring_later_warns(tmp_path: Path, days: int, level: str | None) -> None:
    found, examined = expiry().model_findings(catalogue_retiring_in(tmp_path, days), TODAY)
    assert examined >= 1
    assert [f.level for f in found if f.what.startswith("model")] == ([level] if level else [])
