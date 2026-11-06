"""The post-deploy smoke lane (tests/smoke/smoke.py) passes a good deployment and fails each fault it exists for,
and never sends anything but GET (06/T1, 07/O3, README #14). Offline: a local stub plays the deployed app."""

from __future__ import annotations

import importlib.util
import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any, ClassVar

import pytest

ROOT = Path(__file__).resolve().parents[4]
SHA = "c" * 40
PREFIX = ""


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("smoke_lane", ROOT / "tests" / "smoke" / "smoke.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Deployed(BaseHTTPRequestHandler):
    """A deployed app, healthy unless a test breaks one answer."""

    answers: ClassVar[dict[str, tuple[int, dict[str, str], Any]]] = {}
    methods: ClassVar[list[str]] = []

    @classmethod
    def healthy(cls) -> None:
        csp = "default-src 'self'; script-src 'self' 'nonce-abc'; object-src 'none'"
        problem = {"Content-Type": "application/problem+json"}
        cls.answers = {
            f"{PREFIX}/health": (200, {}, {"status": "ok", "sha": SHA}),
            f"{PREFIX}/ready": (200, {}, {"status": "ready", "checks": {}}),
            f"{PREFIX}/work-items": (401, problem, {"title": "Unauthorized", "status": 401}),
            "/": (200, {"Content-Security-Policy": csp, "X-Content-Type-Options": "nosniff"}, "<html></html>"),
        }
        cls.methods = []

    def _answer(self) -> None:
        Deployed.methods.append(self.command)
        status, headers, body = Deployed.answers.get(self.path, (404, {}, {}))
        payload = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(status)
        for name, value in {"Content-Type": "application/json", **headers}.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _answer  # so any method would be seen

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def app() -> Iterator[str]:
    Deployed.healthy()
    server = HTTPServer(("127.0.0.1", 0), Deployed)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def smoke(base: str, sha: str | None = SHA, tries: int = 3) -> int:
    lane = load()
    lane.TRIES = tries
    args = ["--base-url", base, "--web-url", base]
    code: int = lane.main([*args, *(["--sha", sha] if sha else [])])
    return code


def test_a_good_deployment_passes_and_is_only_read(app: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert smoke(app) == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert "examined 4 checks" in out and "0 failed" in out, out
    assert Deployed.methods and set(Deployed.methods) == {"GET"}, f"smoke must never write: {Deployed.methods}"


@pytest.mark.parametrize(
    ("path", "answer", "expected"),
    [
        (f"{PREFIX}/health", (200, {}, {"status": "ok", "sha": "d" * 40}), "the wrong build is serving"),
        (f"{PREFIX}/health", (503, {}, {}), "/health answered 503"),
        (f"{PREFIX}/ready", (503, {}, {"checks": {"migration": "at 0002, code expects 0001"}}), "code expects"),
        (f"{PREFIX}/work-items", (200, {}, {"items": []}), "not refusing strangers"),
        ("/", (200, {"Content-Security-Policy": "script-src 'self' 'unsafe-inline'"}, ""), "allows inline scripts"),
        ("/", (200, {}, ""), "no script-src"),
        ("/", (502, {}, ""), "the web root answered 502"),
    ],
)
def test_each_fault_fails_the_smoke_and_is_named(
    app: str, capsys: pytest.CaptureFixture[str], path: str, answer: tuple[int, dict[str, str], Any], expected: str
) -> None:
    Deployed.answers[path] = answer
    assert smoke(app) == 1
    out = capsys.readouterr().out
    assert expected in out and "1 failed" in out, out


def test_without_an_expected_sha_the_build_must_still_show_one(app: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert smoke(app, sha=None) == 0
    Deployed.answers[f"{PREFIX}/health"] = (200, {}, {"status": "ok", "sha": "unknown"})
    assert smoke(app, sha=None) == 1
    assert "not a git SHA" in capsys.readouterr().out


def test_an_unreachable_deployment_fails() -> None:
    assert smoke("http://127.0.0.1:9", tries=1) == 1
