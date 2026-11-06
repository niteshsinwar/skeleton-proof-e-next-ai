"""The web image holds only the standalone server and serves its own built assets (07/O1, 03/F24, F38, F48; 12/N10).

A system lane (12/N5), like test_api_image.py: it builds the real image and plants secret-looking files first.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Iterator

import pytest
from imagelane import build, docker, files_in, get, planted, require_docker, run_detached, user_of, wait_for

require_docker()

SHA = secrets.token_hex(20)
# Inside apps/web, which the Dockerfile copies, so only the .dockerignore keeps them out (06/T7).
PLANTED = [
    "apps/web/.env.local",
    "apps/web/.dev-keys/planted.json",
    "apps/web/lib/planted-signing.pem",
    "apps/web/lib/planted.key",
]


@pytest.fixture(scope="module")
def image() -> Iterator[str]:
    tag = f"skeleton-proof-e-next-ai-web:test-{SHA[:12]}"
    with planted(PLANTED):
        build("apps/web/Dockerfile", tag, SHA)
    yield tag
    docker("rmi", "-f", tag, check=False)


def test_the_image_holds_only_the_standalone_server(image: str) -> None:
    names = [n for n in files_in(image) if n.startswith("app/")]
    own = [n for n in names if "/node_modules/" not in n]
    print(f"image content: examined {len(names)} files under /app, {len(own)} outside node_modules")
    assert "app/server.js" in names, "the standalone server is missing (03/F24)"
    assert any(n.startswith("app/.next/static/") for n in names), "the built static assets are missing (03/F24)"
    leaked = [n for n in names if re.search(r"(^|/)\.env($|\.)|planted|/\.dev-keys(/|$)", n)]
    leaked += [n for n in own if re.search(r"\.pem$|\.key$|/tests(/|$)|\.(tsx?|mts)$", n)]
    assert not leaked, f"files that must never be in an image (12/N10, 07/O1): {leaked[:10]}"
    assert user_of(image) == "node", "the image runs as root"


def test_the_runtime_ships_node_without_npm(image: str) -> None:
    """05/SG13: npm's own bundled dependencies carried High advisories (Grype, first CI run on GitHub), and the server
    never runs npm, so the runtime image ships node alone."""
    names = files_in(image)
    global_tools = ("usr/local/lib/node_modules/", "usr/local/bin/np", "usr/local/bin/corepack")
    npm = [n for n in names if n.startswith(global_tools)]
    print(f"image content: examined {len(names)} entries for npm")
    assert "usr/local/bin/node" in names, "node itself is missing from the runtime image"
    assert not npm, f"npm is in the runtime image: {npm[:5]}"


def test_the_release_sha_is_in_the_shipped_bundle(image: str) -> None:
    """03/F48: error reports name the build they came from, so the SHA is baked into the client bundle."""
    found = docker("run", "--rm", "--entrypoint", "grep", image, "-rl", SHA, "/app/.next/static", check=False)
    assert found.returncode == 0 and found.stdout.strip(), "BUILD_SHA did not reach the client bundle"


def test_the_server_serves_its_assets_with_a_nonce_csp(image: str) -> None:
    chunk = next(n for n in files_in(image) if n.startswith("app/.next/static/chunks/") and n.endswith(".js"))
    container, base = run_detached(image, 3000)
    try:
        wait_for(f"{base}/__no-such-page", container, expect=404)
        status, headers, _ = get(f"{base}/{chunk.removeprefix('app/').replace('.next', '_next', 1)}")
        assert status == 200, f"the built artefact does not serve its own assets (03/F24): {chunk}"
        status, headers, _ = get(f"{base}/__no-such-page")
        csp = headers.get("content-security-policy", "")
        script_src = csp.split("script-src", 1)[1].split(";", 1)[0] if "script-src" in csp else ""
        assert status == 404 and "nonce-" in script_src, f"no per-request nonce on scripts (03/F38): {csp!r}"
        assert "'unsafe-inline'" not in script_src, f"inline scripts allowed (03/F38): {csp!r}"
        assert headers.get("x-content-type-options") == "nosniff", headers
    finally:
        docker("rm", "-f", container, check=False)
