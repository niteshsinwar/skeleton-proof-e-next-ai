"""The local mock issuer enforces the parts of OIDC the app relies on (13/SK4): PKCE S256, exact redirect URI,
single-use codes, and tokens the API itself accepts. Development tooling, tested like code (10/H12)."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import secrets
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "mock_oidc.py"
REDIRECT = "http://127.0.0.1:3999/auth/callback"


@pytest.fixture(scope="module")
def issuer(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Any]:
    spec = importlib.util.spec_from_file_location("mock_oidc", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mock_oidc"] = mod  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(mod)
    mod.KEYS = tmp_path_factory.mktemp("keys")  # never touch the developer's real dev keys
    server = mod.serve(0, [f"web:s3cret:{REDIRECT}"])
    port = server.server_address[1]
    server.issuer.url = f"http://127.0.0.1:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.issuer
    server.shutdown()


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _code(issuer: Any, challenge: str, redirect: str = REDIRECT, user: str = "bob") -> str:
    r = httpx.get(
        f"{issuer.url}/authorize",
        params={
            "response_type": "code",
            "client_id": "web",
            "redirect_uri": redirect,
            "state": "st",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "nonce": "n1",
            "login_hint": user,
        },
    )
    assert r.status_code == 302, r.text
    query = parse_qs(urlparse(r.headers["location"]).query)
    assert query["state"] == ["st"]
    return query["code"][0]


def _token(issuer: Any, code: str, verifier: str, redirect: str = REDIRECT) -> httpx.Response:
    return httpx.post(
        f"{issuer.url}/token",
        auth=("web", "s3cret"),
        data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect, "code_verifier": verifier},
    )


def test_code_flow_yields_tokens_the_api_would_accept(issuer: Any) -> None:
    verifier, challenge = _pkce()
    r = _token(issuer, _code(issuer, challenge), verifier)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    key = jwt.PyJWKSet.from_dict(httpx.get(f"{issuer.url}/jwks").json())["mock-issuer-1"].key
    access = jwt.decode(r.json()["access_token"], key, algorithms=["RS256"], audience="app-api", issuer=issuer.url)
    ident = jwt.decode(r.json()["id_token"], key, algorithms=["RS256"], audience="web", issuer=issuer.url)
    assert access["sub"] == "bob" and "tid" in access and "roles" not in access  # identity only (02/Z5)
    assert access["name"] == "Bob"  # the API shows names, never subjects (03/F16)
    assert ident["nonce"] == "n1" and "roles" not in ident  # nor does the ID token carry roles


def test_wrong_verifier_reused_code_and_wrong_redirect_are_refused(issuer: Any) -> None:
    verifier, challenge = _pkce()
    code = _code(issuer, challenge)
    assert _token(issuer, code, "not-the-verifier").json()["error"] == "invalid_grant"
    reused = _token(issuer, code, verifier).json()
    assert reused["error"] == "invalid_grant", "a code is single-use, even after a failed exchange"
    verifier, challenge = _pkce()
    code = _code(issuer, challenge)
    assert _token(issuer, code, verifier, "http://127.0.0.1:3999/elsewhere").json()["error"] == "invalid_grant"


def test_authorize_requires_pkce_and_an_exact_redirect(issuer: Any) -> None:
    base = {"response_type": "code", "client_id": "web", "redirect_uri": REDIRECT, "state": "s", "login_hint": "alice"}
    assert httpx.get(f"{issuer.url}/authorize", params=base).status_code == 400
    _, challenge = _pkce()
    other = {**base, "redirect_uri": REDIRECT + "x", "code_challenge": challenge, "code_challenge_method": "S256"}
    assert httpx.get(f"{issuer.url}/authorize", params=other).status_code == 400


def test_discovery_names_itself_as_issuer(issuer: Any) -> None:
    meta = httpx.get(f"{issuer.url}/.well-known/openid-configuration").json()
    assert meta["issuer"] == issuer.url and meta["code_challenge_methods_supported"] == ["S256"]
