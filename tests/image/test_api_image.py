"""The API image holds only what runs, starts as it should and migrates itself (07/O1, O2, O4; 12/N10).

A system lane (12/N5): it builds the real image from the repository root with Docker. `make test-image` runs it;
without a Docker daemon it skips loudly, and REQUIRE_DOCKER=1 (CI) turns the skip into an error, like REQUIRE_DB.
Every run plants secret-looking files in the build context first, so the .dockerignore is tested, not trusted.
"""

from __future__ import annotations

import json
import re
import secrets
import time
from collections.abc import Iterator

import pytest
from imagelane import ROOT, build, docker, files_in, get, planted, require_docker, run_detached, user_of, wait_for

require_docker()

PKG = "skeleton_proof_e_next_ai"
SHA = secrets.token_hex(20)  # a fake but well-formed git SHA, so /health must report exactly what was baked in
# Files that must never reach an image (12/N10), planted inside the folders the Dockerfile copies (06/T7).
PLANTED = [
    f"apps/api/src/{PKG}/.env",
    "apps/api/config/.env.production",
    f"apps/api/src/{PKG}/.dev-keys/planted.json",
    "apps/api/config/planted-signing.pem",
    f"apps/api/src/{PKG}/planted.key",
    "ai/.env.local",
]
REQUIRED = [
    "app/apps/api/alembic.ini",
    f"app/apps/api/src/{PKG}/run.py",
    "app/apps/api/config",
    f"app/apps/api/src/{PKG}/persistence/migrations/env.py",
    "app/ai/models.yaml",
]


@pytest.fixture(scope="module")
def image() -> Iterator[str]:
    tag = f"{PKG.replace('_', '-')}-api:test-{SHA[:12]}"
    with planted(PLANTED):
        build("apps/api/Dockerfile", tag, SHA)
    yield tag
    docker("rmi", "-f", tag, check=False)


def test_the_image_holds_only_what_runs(image: str) -> None:
    names = [n for n in files_in(image) if n.startswith("app/")]
    print(f"image content: examined {len(names)} files under /app")
    assert len(names) > 100, "the content test is not seeing the image"
    # Anywhere in the image: an environment file or anything this test planted. In the project's own tree (not the
    # third-party packages under .venv, which ship CA bundles and their own tests): key material and tests too.
    own = [n for n in names if not n.startswith("app/.venv/")]
    leaked = [n for n in names if re.search(r"(^|/)\.env($|\.)|planted", n)]
    leaked += [n for n in own if re.search(r"\.pem$|\.key$|/\.dev-keys(/|$)|/tests(/|$)", n)]
    print(f"image content: {len(own)} of them the project's own")
    assert own, "the content test is not seeing the project's own files"
    assert not leaked, f"files that must never be in an image (12/N10, 07/O1): {leaked[:10]}"
    missing = [r for r in REQUIRED if not any(n == r or n.startswith(r + "/") for n in names)]
    assert not missing, f"runtime files missing from the image (07/O1): {missing}"
    assert user_of(image) == "app", "the image runs as root"


def test_the_environment_is_never_assumed(image: str) -> None:
    result = docker("run", "--rm", image, "config-check", check=False)
    assert result.returncode == 2 and "APP_ENV is not set" in result.stderr, result.stderr


def test_a_deployed_environment_refuses_development_settings(image: str) -> None:
    result = docker("run", "--rm", "-e", "APP_ENV=staging", image, "config-check", check=False)
    assert result.returncode == 1, result.stdout
    assert "APP_AUTH_JWKS_FILE" in result.stdout and "APP_AUTH_ISSUER" in result.stdout, result.stdout
    started = docker("run", "--rm", "-e", "APP_ENV=staging", image, "api", check=False, timeout=60)
    assert started.returncode != 0 and "refusing to start in staging" in started.stderr, started.stderr[-1000:]


def postgres_image() -> str:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    match = re.search(r"^\s+image:\s*(\S+)", compose, re.M)
    assert match, "compose.yaml names no Postgres image"
    return match.group(1)


def serve(image: str, url: str, network: str, command: str = "api") -> tuple[str, str]:
    args = ("--network", network, "-e", "APP_ENV=test", "-e", url)
    container, base = run_detached(image, 8000, *args, command=(command,))
    wait_for(f"{base}{'/api' if command == 'web' else ''}/health", container)
    return container, base


def test_the_image_shows_its_build_and_migrates_itself_before_it_is_ready(image: str) -> None:
    """/health shows the baked SHA (02/A12); /ready stays false until `migrate`, run by the image itself, brings
    the schema to the code's head (07/O2). Against a real, empty Postgres: the image is never trusted without one."""
    network = f"probe-{SHA[:12]}"
    docker("network", "create", network)
    db = docker(
        "run", "-d", "--network", network, "--network-alias", "db", "-e", "POSTGRES_USER=app_owner",
        "-e", "POSTGRES_PASSWORD=probe-only", "-e", "POSTGRES_DB=app", postgres_image(),
    ).stdout.strip()  # fmt: skip
    url = "APP_DATABASE_URL=postgresql+psycopg://app_owner:probe-only@db:5432/app"
    container = None
    try:
        for _ in range(60):
            if docker("exec", db, "pg_isready", "-U", "app_owner", "-d", "app", check=False).returncode == 0:
                break
            time.sleep(0.5)
        time.sleep(1)  # the image's init restarts the server once before it accepts connections for good
        # Before migrations this project's API refuses to start at all: its workflow checkpointer connects as the
        # app role, which only the migration creates. Fail closed (README #6); it never serves an unmigrated schema.
        early = docker(
            "run", "--rm", "--network", network, "-e", "APP_ENV=test", "-e", url, image, "api", check=False, timeout=90
        )
        assert early.returncode != 0 and "app_user" in early.stderr, f"started on an unmigrated database: {early}"
        migrated = docker(
            "run", "--rm", "--network", network, "-e", "APP_ENV=test", "-e", url, image, "migrate", check=False
        )
        assert migrated.returncode == 0 and "at head" in migrated.stdout, migrated.stderr[-2000:]
        container, base = serve(image, url, network)
        status, _, body = get(f"{base}/health")
        assert status == 200 and json.loads(body)["sha"] == SHA, f"/health must show the baked SHA (02/A12): {body!r}"
        status, _, body = get(f"{base}/ready")
        assert status == 200 and json.loads(body)["checks"]["migration"] == "ok", f"/ready after migrations: {body!r}"
    finally:
        if container:
            docker("rm", "-f", container, check=False)
        docker("rm", "-f", db, check=False)
        docker("network", "rm", network, check=False)
