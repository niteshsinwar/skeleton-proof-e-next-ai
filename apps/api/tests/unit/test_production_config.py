"""A deployed API refuses development settings (07/O4, README #6): config/production.py, paired both ways (06/T6)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from skeleton_proof_e_next_ai.config import production
from skeleton_proof_e_next_ai.config.settings import Settings

PUBLIC_KEY = {"kty": "OKP", "crv": "Ed25519", "x": "11qYAYKxCrfVS_7TyWQHOg7hcvPapiMlrwIaaPcHURo", "kid": "k1"}


def safe(tmp_path: Path, **changes: Any) -> Settings:
    """A configuration that may serve production; each test changes one thing."""
    jwks = tmp_path / "jwks.json"
    jwks.write_text(json.dumps({"keys": [PUBLIC_KEY]}), encoding="utf-8")
    values: dict[str, Any] = {
        "env": "production",
        "build_sha": "0123456789abcdef0123456789abcdef01234567",
        "auth_jwks_file": jwks,
        "auth_issuer": "https://id.example.com",
        "rate_limit_store": "postgres",
        "mcp_resource_url": "https://app.example.com/mcp",
        "mcp_allowed_hosts": ["app.example.com"],
        "upload_dir": tmp_path / "uploads-volume",
    }
    return Settings(**{**values, **changes})


def test_a_safe_production_configuration_has_no_problems(tmp_path: Path) -> None:
    assert production.problems(safe(tmp_path)) == []


def test_local_and_test_are_never_checked(tmp_path: Path) -> None:
    assert production.problems(safe(tmp_path, env="local", build_sha="unknown")) == []
    assert production.problems(safe(tmp_path, env="test", build_sha="unknown")) == []


@pytest.mark.parametrize("env", ["staging", "production"])
def test_an_unknown_build_sha_is_refused(tmp_path: Path, env: str) -> None:
    found = production.problems(safe(tmp_path, env=env, build_sha="unknown"))
    assert len(found) == 1 and "APP_BUILD_SHA" in found[0]


def test_a_missing_jwks_is_refused(tmp_path: Path) -> None:
    found = production.problems(safe(tmp_path, auth_jwks_file=tmp_path / "absent.json"))
    assert len(found) == 1 and "names no file" in found[0]


def test_a_jwks_holding_a_private_key_is_refused(tmp_path: Path) -> None:
    jwks = tmp_path / "leaked.json"
    jwks.write_text(json.dumps({"keys": [{**PUBLIC_KEY, "d": "private-part"}]}), encoding="utf-8")
    found = production.problems(safe(tmp_path, auth_jwks_file=jwks))
    assert len(found) == 1 and "private key" in found[0]


def test_an_empty_jwks_is_refused(tmp_path: Path) -> None:
    jwks = tmp_path / "empty.json"
    jwks.write_text(json.dumps({"keys": []}), encoding="utf-8")
    found = production.problems(safe(tmp_path, auth_jwks_file=jwks))
    assert len(found) == 1 and "no keys" in found[0]


@pytest.mark.parametrize("issuer", ["local-dev", "http://id.example.com", "https://localhost"])
def test_a_development_issuer_is_refused(tmp_path: Path, issuer: str) -> None:
    found = production.problems(safe(tmp_path, auth_issuer=issuer))
    assert len(found) == 1 and "APP_AUTH_ISSUER" in found[0]


def test_in_process_rate_limits_follow_the_tier(tmp_path: Path) -> None:
    found = production.problems(safe(tmp_path, rate_limit_store="memory"))
    assert len(found) == 1 and "APP_RATE_LIMIT_STORE" in found[0]


def test_the_mcp_server_needs_its_public_url(tmp_path: Path) -> None:
    found = production.problems(safe(tmp_path, mcp_allowed_hosts=["localhost:8000"]))
    assert len(found) == 1 and "MCP_ALLOWED_HOSTS" in found[0]


def test_uploads_inside_the_source_tree_are_refused(tmp_path: Path) -> None:
    inside = Settings().business_config_dir.parent / ".uploads"
    found = production.problems(safe(tmp_path, upload_dir=inside))
    assert len(found) == 1 and "APP_UPLOAD_DIR" in found[0]
