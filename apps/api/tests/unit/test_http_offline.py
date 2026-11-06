"""HTTP behaviour that needs no database: problem details and token verification (02/A6, 02/Z1)."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from skeleton_proof_e_next_ai.api.app import create_app
from skeleton_proof_e_next_ai.api.auth import TokenVerifier, to_principal

from ..conftest import settings_for

pytestmark = pytest.mark.anyio


@pytest.mark.covers("GET /health")
async def test_health_reports_the_build_sha(tmp_path: Path, jwks_file: Path) -> None:
    app = create_app(settings_for(tmp_path, jwks_file, build_sha="abc1234"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/health")
    assert r.json() == {"status": "ok", "sha": "abc1234"}
    assert r.headers["x-request-id"]


async def test_unknown_route_is_a_problem_document(offline_client: httpx.AsyncClient) -> None:
    r = await offline_client.get("/nope")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["code"] == "not-found" and body["correlation_id"] == r.headers["x-request-id"]
    assert "Traceback" not in r.text


async def test_no_token_is_401(offline_client: httpx.AsyncClient) -> None:
    r = await offline_client.get("/work-items")
    assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Bearer")


async def test_unconfigured_jwks_rejects_everything(tmp_path: Path, make_token: Callable[..., str]) -> None:
    app = create_app(settings_for(tmp_path, tmp_path / "missing-jwks.json"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/work-items", headers={"Authorization": f"Bearer {make_token('alice')}"})
    assert r.status_code == 401  # no bypass flag: no JWKS means no access (02/Z1)


@pytest.mark.parametrize("change", ["wrong-key", "wrong-aud", "wrong-iss", "expired", "alg-none", "no-tenant"])
async def test_bad_tokens_are_401(
    offline_client: httpx.AsyncClient, make_token: Callable[..., str], change: str
) -> None:
    if change == "wrong-key":
        token = jwt.encode(
            {"sub": "a", "iss": "test-issuer", "aud": "test-api", "exp": 9_999_999_999, "tid": "x"},
            Ed25519PrivateKey.generate(),
            algorithm="EdDSA",
            headers={"kid": "test-1"},
        )
    elif change == "alg-none":
        token = jwt.encode(
            {"sub": "a", "iss": "test-issuer", "aud": "test-api", "exp": 9_999_999_999},
            None,
            algorithm="none",
            headers={"kid": "test-1"},
        )
    elif change == "no-tenant":
        token = make_token("alice", tid=None)
    else:
        overrides = {"wrong-aud": {"aud": "other"}, "wrong-iss": {"iss": "evil"}, "expired": {"exp": 1}}[change]
        token = make_token("alice", **overrides)
    r = await offline_client.get("/work-items", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401, r.text


async def test_an_unreadable_revocation_list_fails_closed(
    offline_client: httpx.AsyncClient, make_token: Callable[..., str]
) -> None:
    """A valid token is not enough when the revoked-token list can't be read: 503, never a pass (02/Z4, 02/B7)."""
    r = await offline_client.get("/work-items", headers={"Authorization": f"Bearer {make_token('alice')}"})
    assert r.status_code == 503 and r.json()["code"] == "auth-unavailable", r.text
    assert r.headers.get("retry-after")


def test_step_up_needs_a_phishing_resistant_method_used_recently() -> None:
    """02/Z3, Z4: `amr` must name a hardware or software key, and `auth_time` must be inside the window."""
    verifier = TokenVerifier(None, "i", "a", ("EdDSA",), step_up_seconds=900)
    now = int(time.time())
    assert verifier._stepped_up({"amr": ["pwd", "hwk"], "auth_time": now})
    assert not verifier._stepped_up({"amr": ["pwd"], "auth_time": now})  # a password alone is not phishing-resistant
    assert not verifier._stepped_up({"amr": ["hwk"], "auth_time": now - 3600})  # too long ago: sign in again
    assert not verifier._stepped_up({"amr": ["hwk"]})  # no auth_time, no step-up


def test_the_tenant_claim_follows_the_provider() -> None:
    """Providers name the tenant claim differently; the setting says which one this project trusts."""
    org = "00000000-0000-0000-0000-0000000000c1"
    assert to_principal({"sub": "a", "org_id": org}, tenant_claim="org_id").tenant_id == UUID(org)
