#!/usr/bin/env python3
"""Mint a local-only development token (05/SG12: dev tokens are labelled and invalid anywhere else).

  uv run --project apps/api python scripts/dev_token.py --sub alice
  uv run --project apps/api python scripts/dev_token.py --sub bot-7 --act-for alice --scope work_item.create

The first run creates an Ed25519 key pair in apps/api/.dev-keys/ (gitignored, unreadable by agents) and the
public JWKS the API pins via APP_AUTH_JWKS_FILE. Tokens carry identity only; give roles with `make grant`. Tokens are issued by "local-dev", so a production API,
which pins its real identity provider, rejects them.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

KEYS = Path(__file__).resolve().parents[1] / "apps" / "api" / ".dev-keys"
KID = "local-dev-1"


def keypair() -> Ed25519PrivateKey:
    private = KEYS / "private.pem"
    if not private.is_file():
        KEYS.mkdir(mode=0o700, parents=True, exist_ok=True)
        key = Ed25519PrivateKey.generate()
        private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()))
        private.chmod(0o600)
        jwk = json.loads(jwt.algorithms.OKPAlgorithm.to_jwk(key.public_key()))
        (KEYS / "jwks.json").write_text(json.dumps({"keys": [{**jwk, "kid": KID, "alg": "EdDSA", "use": "sig"}]}))
    loaded = serialization.load_pem_private_key(private.read_bytes(), password=None)
    assert isinstance(loaded, Ed25519PrivateKey)
    return loaded


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--sub", required=True)
    p.add_argument("--tenant", default="00000000-0000-0000-0000-000000000001")
    p.add_argument("--name", help="the display name screens show (defaults to the subject, capitalised)")
    p.add_argument("--act-for", help="make this an agent token acting for this user")
    p.add_argument("--service", action="store_true", help="make this a service-principal token")
    p.add_argument("--scope", help="space-separated scopes (agents and services)")
    p.add_argument("--issuer", default="local-dev", help="match the API's APP_AUTH_ISSUER")
    p.add_argument("--minutes", type=int, default=60)
    p.add_argument("--step-up", action="store_true", help="as if just signed in with a passkey (privileged acts, 02/Z3)")
    p.add_argument("--init-only", action="store_true", help="create the key pair and JWKS, print nothing")
    a = p.parse_args()
    key = keypair()
    if a.init_only:
        return
    now = int(time.time())
    claims: dict[str, object] = {"iss": a.issuer, "aud": "app-api", "iat": now, "exp": now + 60 * a.minutes,
                                 "sub": a.act_for or a.sub, "tid": a.tenant,  # identity only: roles live in grants
                                 "name": a.name or (a.act_for or a.sub).capitalize()}
    if a.step_up:
        claims["amr"], claims["auth_time"] = ["pwd", "hwk"], now
    if a.act_for:
        claims["act"] = {"sub": a.sub}
    if a.service:
        claims["kind"] = "service"
    if a.scope:
        claims["scope"] = a.scope
    print(jwt.encode(claims, key, algorithm="EdDSA", headers={"kid": KID}))


if __name__ == "__main__":
    main()
