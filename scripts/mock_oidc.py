#!/usr/bin/env python3
"""MOCK OpenID Connect issuer for local development and tests only (13/SK4). Never deploy it.

  uv run --project apps/api python scripts/mock_oidc.py --port 9400 \
      --client web:local-dev-secret:http://127.0.0.1:3000/auth/callback

It binds to 127.0.0.1 only and implements just enough of OIDC for the real flow to be exercised end to end:
discovery, /authorize (pick a dev user; `login_hint` skips the page for tests), /token (authorization code +
PKCE S256, exact redirect URI, single-use codes valid 60 s), /jwks. Tokens are RS256. The access token's audience
is `app-api`, which the API pins; the ID token's audience is the client id. Its public key is merged into
apps/api/.dev-keys/jwks.json so the API verifies these tokens too.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import secrets
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urlparse

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

KEYS = Path(__file__).resolve().parents[1] / "apps" / "api" / ".dev-keys"
KID = "mock-issuer-1"
TENANT = "00000000-0000-0000-0000-000000000001"
# Who can sign in, by display name. Their roles are granted in the API's database (`make grant`), never here (02/Z5).
USERS: dict[str, dict[str, Any]] = {"alice": {"name": "Alice"}, "bob": {"name": "Bob"}, "root": {"name": "Root"}}
CODE_TTL = 60


@dataclass
class Client:
    client_id: str
    secret: str | None
    redirect_uri: str


@dataclass
class Issuer:
    url: str
    clients: dict[str, Client]
    key: rsa.RSAPrivateKey
    codes: dict[str, dict[str, Any]] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def jwk(self) -> dict[str, Any]:
        public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        return {**public, "kid": KID, "alg": "RS256", "use": "sig"}

    def discovery(self) -> dict[str, Any]:
        return {
            "issuer": self.url,
            "authorization_endpoint": f"{self.url}/authorize",
            "token_endpoint": f"{self.url}/token",
            "jwks_uri": f"{self.url}/jwks",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "code_challenge_methods_supported": ["S256"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post", "none"],
            "scopes_supported": ["openid", "profile"],
        }

    def issue_code(self, client: Client, user: str, params: dict[str, str]) -> str:
        code = secrets.token_urlsafe(32)
        with self.lock:
            self.codes[code] = {"client_id": client.client_id, "user": user, "redirect_uri": params["redirect_uri"],
                                "challenge": params["code_challenge"], "nonce": params.get("nonce"),
                                "expires": time.time() + CODE_TTL}
        return code

    def redeem(self, code: str, client: Client, redirect_uri: str, verifier: str) -> dict[str, Any]:
        with self.lock:
            entry = self.codes.pop(code, None)  # single use, whatever happens next
        if entry is None or entry["expires"] < time.time():
            raise ValueError("unknown, used or expired code")
        if entry["client_id"] != client.client_id or entry["redirect_uri"] != redirect_uri:
            raise ValueError("code was issued to another client or redirect URI")
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        if not secrets.compare_digest(challenge, entry["challenge"]):
            raise ValueError("PKCE verifier does not match")
        now, user = int(time.time()), entry["user"]
        common = {"iss": self.url, "sub": user, "iat": now, "exp": now + 900, "name": USERS[user]["name"]}
        # Identity only: the API holds roles (02/Z5). The mock simulates a passkey sign-in, so step-up passes (02/Z3).
        access = {**common, "aud": "app-api", "tid": TENANT, "amr": ["pwd", "hwk"], "auth_time": now}
        id_token = {**common, "aud": client.client_id}
        if entry["nonce"]:
            id_token["nonce"] = entry["nonce"]
        sign = lambda claims: jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": KID})  # noqa: E731
        return {"access_token": sign(access), "id_token": sign(id_token), "token_type": "Bearer", "expires_in": 900}


def load_key() -> rsa.RSAPrivateKey:
    path = KEYS / "mock-issuer.pem"
    if not path.is_file():
        KEYS.mkdir(mode=0o700, parents=True, exist_ok=True)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
        path.chmod(0o600)
    loaded = serialization.load_pem_private_key(path.read_bytes(), password=None)
    assert isinstance(loaded, rsa.RSAPrivateKey)
    return loaded


def publish_jwk(jwk: dict[str, Any]) -> None:
    """Merge this issuer's public key into the JWKS the API pins (APP_AUTH_JWKS_FILE)."""
    path = KEYS / "jwks.json"
    current = json.loads(path.read_text()) if path.is_file() else {"keys": []}
    keys = [k for k in current["keys"] if k.get("kid") != KID] + [jwk]
    path.write_text(json.dumps({"keys": keys}))


def handler_for(issuer: Issuer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:  # quiet by default
            return

        def _send(self, status: int, body: str | dict[str, Any], ctype: str = "application/json",
                  headers: dict[str, str] | None = None) -> None:
            data = (json.dumps(body) if isinstance(body, dict) else body).encode()
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _error(self, status: int, error: str, description: str) -> None:
            self._send(status, {"error": error, "error_description": description})

        def _form(self) -> dict[str, str]:
            length = int(self.headers.get("Content-Length") or 0)
            return {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode()).items()}

        def _authorize_params(self, params: dict[str, str]) -> Client | None:
            client = issuer.clients.get(params.get("client_id", ""))
            if client is None or params.get("redirect_uri") != client.redirect_uri:
                self._error(400, "invalid_request", "unknown client or redirect URI (exact match required)")
                return None
            if params.get("response_type") != "code" or params.get("code_challenge_method") != "S256" \
                    or not params.get("code_challenge") or not params.get("state"):
                self._error(400, "invalid_request", "code flow with PKCE S256 and a state is required")
                return None
            return client

        def _redirect_with_code(self, client: Client, user: str, params: dict[str, str]) -> None:
            code = issuer.issue_code(client, user, params)
            query = urlencode({"code": code, "state": params["state"], "iss": issuer.url})
            self._send(302, "", "text/plain", {"Location": f"{client.redirect_uri}?{query}"})

        def do_GET(self) -> None:
            url = urlparse(self.path)
            params = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path == "/.well-known/openid-configuration":
                return self._send(200, issuer.discovery())
            if url.path == "/jwks":
                return self._send(200, {"keys": [issuer.jwk]})
            if url.path == "/authorize":
                client = self._authorize_params(params)
                if client is None:
                    return None
                if params.get("login_hint") in USERS:
                    return self._redirect_with_code(client, params["login_hint"], params)
                hidden = "".join(f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">'
                                 for k, v in params.items())
                buttons = "".join(f'<button name="user" value="{u}">{html.escape(d["name"])}</button>'
                                  for u, d in USERS.items())
                page = (f"<!doctype html><html lang=en><title>Mock sign-in</title><main><h1>Mock sign-in</h1>"
                        f"<p>Local development only. Choose a user.</p><form method=post action=/authorize>"
                        f"{hidden}{buttons}</form></main></html>")
                return self._send(200, page, "text/html; charset=utf-8")
            return self._error(404, "not_found", "unknown endpoint")

        def do_POST(self) -> None:
            url, form = urlparse(self.path), self._form()
            if url.path == "/authorize":
                client = self._authorize_params(form)
                if client is None:
                    return None
                if form.get("user") not in USERS:
                    return self._error(400, "access_denied", "choose a known user")
                return self._redirect_with_code(client, form["user"], form)
            if url.path == "/token":
                client_id, secret = form.get("client_id"), form.get("client_secret")
                auth = self.headers.get("Authorization", "")
                if auth.startswith("Basic "):
                    raw = base64.b64decode(auth[6:]).decode()
                    client_id, secret = (unquote(p) for p in raw.split(":", 1))
                client = issuer.clients.get(client_id or "")
                if client is None or (client.secret is not None and not secrets.compare_digest(secret or "", client.secret)):
                    return self._error(401, "invalid_client", "client authentication failed")
                if form.get("grant_type") != "authorization_code":
                    return self._error(400, "unsupported_grant_type", "only authorization_code is supported")
                try:
                    tokens = issuer.redeem(form.get("code", ""), client, form.get("redirect_uri", ""),
                                           form.get("code_verifier", ""))
                except ValueError as exc:
                    return self._error(400, "invalid_grant", str(exc))
                return self._send(200, tokens)
            return self._error(404, "not_found", "unknown endpoint")

    return Handler


def serve(port: int, clients: list[str]) -> ThreadingHTTPServer:
    registry = {}
    for spec in clients:
        client_id, secret, redirect = spec.split(":", 2)
        registry[client_id] = Client(client_id, secret or None, redirect)
    url = f"http://127.0.0.1:{port}"
    issuer = Issuer(url=url, clients=registry, key=load_key())
    publish_jwk(issuer.jwk)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler_for(issuer))
    server.issuer = issuer  # type: ignore[attr-defined]
    return server


def main() -> None:
    p = argparse.ArgumentParser(description="MOCK OIDC issuer for local development and tests only.")
    p.add_argument("--port", type=int, default=9400)
    p.add_argument("--client", action="append", default=[],
                   help="client_id:secret:redirect_uri (empty secret = public client); repeatable")
    p.add_argument("--publish-only", action="store_true",
                   help="create the signing key, publish it to the API's JWKS file, and exit (run before the API starts)")
    a = p.parse_args()
    if a.publish_only:
        issuer = Issuer(url=f"http://127.0.0.1:{a.port}", clients={}, key=load_key())
        publish_jwk(issuer.jwk)
        return
    server = serve(a.port, a.client or ["web:local-dev-secret:http://127.0.0.1:3000/auth/callback"])
    print(f"mock OIDC issuer on http://127.0.0.1:{a.port} (development only)", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
