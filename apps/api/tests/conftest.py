"""Shared fixtures. Tokens are real signed JWTs from a throwaway key; the database is real Postgres (06/T4).

Integration tests need TEST_DATABASE_URL (a database used only by this suite, never dev or demo, 06/T10).
Without it they are skipped, unless REQUIRE_DB=1 (CI), which turns the skip into an error (06/T1).
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import jwt
import pytest
from alembic import command
from alembic.config import Config
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import create_engine, text

from skeleton_proof_e_next_ai.api.app import create_app
from skeleton_proof_e_next_ai.config.project import DEFAULT_TENANT, MULTI_TENANT
from skeleton_proof_e_next_ai.config.settings import Settings

API_ROOT = Path(__file__).resolve().parents[1]
TENANT_A = "00000000-0000-0000-0000-00000000000a"
TENANT_B = "00000000-0000-0000-0000-00000000000b"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("TEST_DATABASE_URL"):
        return
    if os.environ.get("REQUIRE_DB") == "1":
        raise pytest.UsageError("REQUIRE_DB=1 but TEST_DATABASE_URL is not set: the integration lane cannot run.")
    skip = pytest.mark.skip(reason="no TEST_DATABASE_URL (integration lane)")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
def signing_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


@pytest.fixture(scope="session")
def jwks_file(tmp_path_factory: pytest.TempPathFactory, signing_key: Ed25519PrivateKey) -> Path:
    jwk = json.loads(jwt.algorithms.OKPAlgorithm.to_jwk(signing_key.public_key()))
    path = tmp_path_factory.mktemp("jwks") / "jwks.json"
    path.write_text(json.dumps({"keys": [{**jwk, "kid": "test-1", "alg": "EdDSA", "use": "sig"}]}))
    return path


@pytest.fixture(scope="session")
def make_token(signing_key: Ed25519PrivateKey) -> Callable[..., str]:
    def make(
        sub: str,
        tenant: str = TENANT_A,
        act: str | None = None,
        scope: str | None = None,
        service: bool = False,
        **overrides: Any,
    ) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": "test-issuer",
            "aud": "test-api",
            "iat": now,
            "exp": now + 600,
            "sub": sub,
            "tid": tenant,
            "amr": ["pwd", "hwk"],  # a passkey sign-in, just now: privileged acts pass step-up (02/Z3)
            "auth_time": now,
        }  # identity only: roles are granted in the database (the `user` fixture, 02/Z5)
        if act:
            claims["act"] = {"sub": act}
        if scope is not None:
            claims["scope"] = scope
        if service:
            claims["kind"] = "service"
        claims.update(overrides)
        return jwt.encode(claims, signing_key, algorithm="EdDSA", headers={"kid": "test-1"})

    return make


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("no TEST_DATABASE_URL")
    return url


@pytest.fixture(scope="session")
def migrated(database_url: str) -> str:
    """A clean schema at the migration head, once per session."""
    engine = create_engine(database_url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS app, audit, jobs, ai, eval, agent_checkpoints, rag CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    engine.dispose()
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")
    return database_url


@pytest.fixture
def user(make_token: Callable[..., str], migrated: str) -> Callable[..., str]:
    """A signed-in person: sets their roles in the database, the only place roles live (02/Z5), and returns a
    token that proves who they are. Calling it again for the same person replaces their roles."""
    engine = create_engine(migrated)

    def make(sub: str, roles: list[str], tenant: str = TENANT_A, **claims: Any) -> str:
        held_in = tenant if MULTI_TENANT else str(DEFAULT_TENANT)
        with engine.begin() as conn:
            # exactly these roles: anything else this person held is revoked, so tests never inherit grants
            conn.execute(
                text(
                    "UPDATE app.role_grants SET revoked_by = 'test', revoked_at = now() WHERE tenant_id = :t "
                    "AND subject = :s AND revoked_at IS NULL AND NOT (role = ANY(:roles))"
                ),
                {"t": held_in, "s": sub, "roles": roles},
            )
            for role in roles:
                conn.execute(
                    text(
                        "INSERT INTO app.role_grants (tenant_id, subject, role, granted_by, granted_at) "
                        "VALUES (:t, :s, :r, 'test', now()) ON CONFLICT (tenant_id, subject, role) "
                        "DO UPDATE SET revoked_by = NULL, revoked_at = NULL"
                    ),
                    {"t": held_in, "s": sub, "r": role},
                )
        return make_token(sub, tenant=tenant, **claims)

    return make


def settings_for(
    tmp_path: Path, jwks_file: Path, database_url: str = "postgresql+psycopg://unused/none", **overrides: Any
) -> Settings:
    defaults: dict[str, Any] = {
        "env": "test",
        "database_url": database_url,
        "auth_jwks_file": jwks_file,
        "auth_issuer": "test-issuer",
        "auth_audience": "test-api",
        "upload_dir": tmp_path / "uploads",
    }
    return Settings(**(defaults | overrides))


@pytest.fixture
async def offline_client(tmp_path: Path, jwks_file: Path) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings_for(tmp_path, jwks_file))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def app_and_client(
    tmp_path: Path, jwks_file: Path, migrated: str
) -> AsyncIterator[tuple[Any, httpx.AsyncClient]]:
    app = create_app(settings_for(tmp_path, jwks_file, migrated))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield app, c
    await app.state.core.db.dispose()


@pytest.fixture
async def client(app_and_client: tuple[Any, httpx.AsyncClient]) -> httpx.AsyncClient:
    return app_and_client[1]


def auth(token: str, **headers: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4()), **headers}
