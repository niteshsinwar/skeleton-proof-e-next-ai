"""Helpers for the image lane (tests/image/): build, inspect and run images with the Docker CLI.

Without a Docker daemon the lane skips loudly; REQUIRE_DOCKER=1 (CI) turns the skip into an error, like REQUIRE_DB.
Not a test module (12/N5): the tests import it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def require_docker() -> None:
    """Skip the calling module without a daemon, or fail it when CI requires one."""
    if shutil.which("docker") is not None:
        probe = subprocess.run(["docker", "info"], capture_output=True, check=False)  # noqa: S607 (fixed argv)
        if probe.returncode == 0:
            return
    if os.environ.get("REQUIRE_DOCKER") == "1":
        raise RuntimeError("REQUIRE_DOCKER=1 but no Docker daemon answers: the image lane cannot run")
    pytest.skip("image lane skipped: no Docker daemon (CI sets REQUIRE_DOCKER=1)", allow_module_level=True)


def docker(*args: str, check: bool = True, timeout: float = 900) -> subprocess.CompletedProcess[str]:
    # The argv is built from fixed words and the tests' own values, never from outside input.
    result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout, check=False)  # noqa: S603, S607
    if check and result.returncode != 0:
        raise AssertionError(f"docker {' '.join(args[:3])} failed ({result.returncode}):\n{result.stderr[-2000:]}")
    return result


@contextmanager
def planted(paths: list[str]) -> Iterator[None]:
    """Secret-looking files in the build context while an image builds, so the .dockerignore is tested, not trusted.

    They must sit inside folders the Dockerfile copies: a file outside them proves the COPY list, not the ignore file.
    """
    made = [ROOT / p for p in paths if not (ROOT / p).exists()]
    for path in made:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("PLANTED=never-in-an-image\n", encoding="utf-8")
    try:
        yield
    finally:
        for path in made:
            path.unlink()


def build(dockerfile: str, tag: str, sha: str) -> None:
    docker("build", "-f", str(ROOT / dockerfile), "--build-arg", f"BUILD_SHA={sha}", "-t", tag, str(ROOT))


def files_in(tag: str) -> list[str]:
    container = docker("create", tag).stdout.strip()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "fs.tar"
            docker("export", "-o", str(archive), container)
            with tarfile.open(archive) as tar:
                return tar.getnames()
    finally:
        docker("rm", container, check=False)


def user_of(tag: str) -> str:
    return str(json.loads(docker("inspect", tag).stdout)[0]["Config"]["User"])


def get(url: str) -> tuple[int, dict[str, str], bytes]:
    """Status, headers (names lower-cased: HTTP header names are case-insensitive) and body; an HTTP error status is a
    result, not an exception."""
    try:
        with urllib.request.urlopen(url, timeout=3) as response:  # noqa: S310  (a local test URL)
            return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read()
    except urllib.error.HTTPError as error:
        return error.code, {k.lower(): v for k, v in error.headers.items()}, error.read()


def run_detached(tag: str, port: int, *args: str, command: tuple[str, ...] = ()) -> tuple[str, str]:
    """Start a container publishing `port` on a free local port; return its id and base URL."""
    container = docker("run", "-d", "-p", f"127.0.0.1::{port}", *args, tag, *command).stdout.strip()
    published = docker("port", container, f"{port}/tcp").stdout.strip().splitlines()[0].rsplit(":", 1)[1]
    return container, f"http://127.0.0.1:{published}"


def wait_for(url: str, container: str, expect: int = 200, tries: int = 90) -> None:
    for _ in range(tries):
        try:
            if get(url)[0] == expect:
                return
        except urllib.error.URLError, ConnectionError:
            pass
        time.sleep(0.5)
    logs = docker("logs", container, check=False)
    docker("rm", "-f", container, check=False)
    raise AssertionError(f"{url} never answered {expect}:\n{logs.stdout[-1000:]}\n{logs.stderr[-2000:]}")
