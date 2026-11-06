"""The OpenAPI document is the contract (02/A11), and every route has a test that names it (10 §5 replay).

`make contracts` regenerates the snapshot; commit it with the route change so the diff is reviewed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from skeleton_proof_e_next_ai.api.app import create_app

from ..conftest import settings_for

API = Path(__file__).resolve().parents[2]
SNAPSHOT = API.parent.parent / "packages" / "contracts" / "openapi.json"
TESTS = API / "tests"


def _routes(tmp_path: Path) -> set[str]:
    """Routes as the contract publishes them. (FastAPI 0.162 no longer flattens included routers into app.routes,
    so scanning app.routes silently sees only the docs routes; the OpenAPI document is the stable interface.)"""
    spec = create_app(settings_for(tmp_path, tmp_path / "jwks.json")).openapi()
    return {f"{method.upper()} {path}" for path, ops in spec["paths"].items() for method in ops}


def test_openapi_matches_the_committed_snapshot(tmp_path: Path) -> None:
    assert SNAPSHOT.is_file(), "packages/contracts/openapi.json is missing: run `make contracts` and commit it"
    live = create_app(settings_for(tmp_path, tmp_path / "jwks.json")).openapi()
    committed = json.loads(SNAPSHOT.read_text())
    assert json.dumps(live, sort_keys=True) == json.dumps(committed, sort_keys=True), (
        "the API contract changed: review the change, run `make contracts`, and commit the snapshot with it"
    )


def test_every_route_has_a_test_naming_it(tmp_path: Path) -> None:
    covered: set[str] = set()
    for f in TESTS.rglob("test_*.py"):
        covered |= set(re.findall(r'covers\("([A-Z]+ /[^"]*)"\)', f.read_text()))
    routes = _routes(tmp_path)
    assert len(routes) >= 10, f"expected the API's routes, found only {sorted(routes)}"
    missing = sorted(routes - covered)
    assert not missing, f"routes with no test naming them (add @pytest.mark.covers(...)): {missing}"
    stale = sorted(covered - routes)
    assert not stale, f"tests claim routes that don't exist: {stale}"
