"""The deploy contract refuses what it must and reverts what fails (07/O1, O3-O6), tested both ways, offline.

scripts/deploy.py is driven against a simulated Docker host (every `docker` call goes through its one `run`), and
GitHub is a local stub server, so each go-live precondition is seen refusing and passing without a cloud. The same
code runs for real on local Docker in `make rehearse-rollback` (in CI too).
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[4]
WEB = True
SHA_A, SHA_B = "a" * 40, "b" * 40
REPO = "ghcr.io/owner/skeleton-proof-e-next-ai"
API_A, API_B = f"{REPO}-api@sha256:{'1' * 64}", f"{REPO}-api@sha256:{'2' * 64}"
WEB_A, WEB_B = f"{REPO}-web@sha256:{'3' * 64}", f"{REPO}-web@sha256:{'4' * 64}"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("deploy_script", ROOT / "scripts" / "deploy.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["deploy_script"] = module  # dataclasses resolve their module by name
    spec.loader.exec_module(module)
    return module


class FakeHost:
    """A Docker host in memory: what runs (with its release labels), what can be pulled, what each step answers."""

    def __init__(self, slug: str) -> None:
        self.slug = slug
        self.labels: dict[str, str] | None = None
        self.pullable = {API_A: SHA_A, API_B: SHA_B, WEB_A: SHA_A, WEB_B: SHA_B}
        self.heads = {API_A: "0001", API_B: "0002"}
        self.db_revision = "0001"
        self.config_problems: list[str] = []
        self.smoke_ok = {SHA_A: True, SHA_B: True}
        self.calls: list[list[str]] = []

    def run(self, argv: list[str], env: dict[str, str] | None = None, stdin: str | None = None) -> Any:  # noqa: PLR0911
        self.calls.append(argv)
        env = env or {}
        done = lambda out="", code=0, err="": subprocess.CompletedProcess(argv, code, out, err)  # noqa: E731
        if "smoke.py" in " ".join(argv):
            sha = argv[argv.index("--sha") + 1]
            return done(code=0 if self.smoke_ok.get(sha) else 1, out=f"smoke checked {sha}\n")
        args = argv[1:]
        if args[:1] == ["ps"]:
            return done("c1\n" if self.labels else "")
        if args[:1] == ["inspect"]:
            labels = {f"{self.slug}.release.{k}": v for k, v in (self.labels or {}).items()}
            container = {"Config": {"Image": (self.labels or {}).get("api-image", ""),
                                    "Labels": {"com.docker.compose.service": "api", **labels}},
                         "State": {"Status": "running", "Health": {"Status": "healthy"}}}  # fmt: skip
            return done(json.dumps([container]))
        if args[:2] == ["pull", "-q"]:
            return done(code=0 if args[2] in self.pullable else 1, err="manifest unknown")
        if args[:2] == ["image", "inspect"]:
            sha = self.pullable.get(args[2], "")
            return done(json.dumps([{"Config": {"Labels": {"org.opencontainers.image.revision": sha}}}]))
        if args[:2] == ["run", "--rm"] and args[-1] == "revision":
            return done(self.heads[args[-2]] + "\n")
        if args[:1] == ["compose"]:
            return self.compose(args, env, done)
        raise AssertionError(f"unexpected command {argv}")

    def compose(self, args: list[str], env: dict[str, str], done: Any) -> Any:
        if "config-check" in args:
            out = "".join(f"config-check: {p}\n" for p in self.config_problems)
            return done(out + "config-check: summary", 1 if self.config_problems else 0)
        if "migrate" in args and "downgrade" in args:
            target = args[args.index("--to") + 1]
            steps = "" if self.db_revision == target else f"downgrade: {self.db_revision} -> {target}\n"
            self.db_revision = target
            return done(steps + f"downgrade: at {target}\n")
        if "migrate" in args:
            self.db_revision = self.heads[env["API_IMAGE"]]
            return done(f"migrate: at head {self.db_revision}\n")
        if "up" in args:
            self.labels = {"api-image": env["API_IMAGE"], "web-image": env.get("WEB_IMAGE", "none"),
                           "previous-api-image": env.get("PREVIOUS_API_IMAGE", "none"),
                           "previous-web-image": env.get("PREVIOUS_WEB_IMAGE", "none"),
                           "sha": env["RELEASE_SHA"], "migration": env["RELEASE_MIGRATION"]}  # fmt: skip
            ready = self.db_revision == self.heads[env["API_IMAGE"]]  # /ready: the schema is this image's head
            return done(code=0 if ready else 1, err="" if ready else "container api is unhealthy")
        if "stop" in args:
            self.labels = None
            return done()
        raise AssertionError(f"unexpected compose command {args}")

    def changes(self) -> list[list[str]]:
        """Calls that change something: anything but reads."""
        reads = (["ps"], ["inspect"], ["image", "inspect"])
        return [c for c in self.calls if not any(c[1 : 1 + len(r)] == r for r in reads)]


class GitHub(BaseHTTPRequestHandler):
    gate = "success"
    reviewers = True

    def do_GET(self) -> None:
        if "/check-runs" in self.path:
            body: dict[str, Any] = {"check_runs": [{"name": "gate", "conclusion": GitHub.gate}] if GitHub.gate else []}
        else:
            body = {"protection_rules": [{"type": "required_reviewers"}] if GitHub.reviewers else []}
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> Iterator[type[GitHub]]:
    server = HTTPServer(("127.0.0.1", 0), GitHub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("GITHUB_API_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GH_TOKEN", "test-token")
    GitHub.gate, GitHub.reviewers = "success", True
    yield GitHub
    server.shutdown()


@pytest.fixture
def d(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ModuleType:
    module = load()
    monkeypatch.setenv("DEPLOY_STATE_DIR", str(tmp_path / "history"))
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    return module


@pytest.fixture
def fake(d: ModuleType, monkeypatch: pytest.MonkeyPatch) -> FakeHost:
    host = FakeHost(d.SLUG)
    monkeypatch.setattr(d, "run", host.run)
    return host


def env_file(tmp_path: Path, **overrides: str) -> Path:
    values = {name: "x" * 32 for name in load().required_names()}
    values |= {"DEPLOY_DATABASE": "managed", "DEPLOY_BASE_URL": "https://api.example.invalid",
               "DEPLOY_WEB_URL": "https://app.example.invalid",
               "APP_MIGRATION_DATABASE_URL": "postgresql+psycopg://app_owner:pw@db.invalid:5432/app",
               "APP_DATABASE_URL": "postgresql+psycopg://app_runtime:pw@db.invalid:5432/app"}  # fmt: skip
    values |= overrides
    path = tmp_path / "production.env"
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items() if v is not None))
    path.chmod(0o600)
    return path


def release(d: ModuleType, api: str = API_B, web: str = WEB_B) -> Any:
    return d.Release(api, web if WEB else None)


def running(fake: FakeHost, api: str = API_A, web: str = WEB_A, sha: str = SHA_A) -> None:
    fake.labels = {"api-image": api, "web-image": web if WEB else "none", "sha": sha, "migration": fake.heads[api],
                   "previous-api-image": "none", "previous-web-image": "none"}  # fmt: skip
    fake.db_revision = fake.heads[api]


def refused(checks: list[dict[str, Any]]) -> list[str]:
    return [str(c["check"]) for c in checks if not c["ok"]]


# -- images are named by digest, never by tag (07/O1) -------------------------------------------------------------
def test_an_image_is_deployed_only_by_digest(d: ModuleType) -> None:
    assert d.image_ref(API_A, None, "API image") == API_A
    assert d.image_ref(f"sha256:{'1' * 64}", f"{REPO}-api", "API image") == API_A
    for bad in (f"{REPO}-api:latest", f"{REPO}-api:v1.2.3", "", None, f"sha256:{'1' * 64}"):
        with pytest.raises(d.Refused):
            d.image_ref(bad, None, "API image")


# -- the host env file (07/O1, O3) ----------------------------------------------------------------------------------
def test_the_env_file_must_be_outside_the_tree_private_and_for_this_environment(d: ModuleType, tmp_path: Path) -> None:
    good = env_file(tmp_path)
    assert d.ComposeHost("production", good).values["DEPLOY_DATABASE"] == "managed"
    inside = ROOT / ".deploy-test.env"
    shutil.copy(good, inside)
    inside.chmod(0o600)
    try:
        with pytest.raises(d.Refused, match="inside the repository"):
            d.ComposeHost("production", inside)
    finally:
        inside.unlink()
    good.chmod(0o644)
    with pytest.raises(d.Refused, match="readable by other users"):
        d.ComposeHost("production", good)
    with pytest.raises(d.Refused, match="APP_ENV=staging but this deploys production"):
        d.ComposeHost("production", env_file(tmp_path, APP_ENV="staging"))


def test_required_settings_come_from_the_compose_file_and_are_checked_by_name(d: ModuleType, tmp_path: Path) -> None:
    names = d.required_names()
    assert {"APP_DATABASE_URL", "APP_MIGRATION_DATABASE_URL", "APP_AUTH_ISSUER", "APP_CONFIG_DIR"} <= set(names)
    assert "API_IMAGE" not in names and "APP_ENV" not in names, "the script sets these itself"
    assert d.ComposeHost("production", env_file(tmp_path)).secrets_problems() == []
    host = d.ComposeHost("production", env_file(tmp_path, APP_AUTH_ISSUER=""))
    assert host.secrets_problems() == ["APP_AUTH_ISSUER is not set in the env file"]
    owner = "postgresql+psycopg://app_owner:pw@db.invalid:5432/app"
    problems = d.ComposeHost("production", env_file(tmp_path, APP_DATABASE_URL=owner)).secrets_problems()
    assert any("schema owner" in p for p in problems), problems
    problems = d.ComposeHost("production", env_file(tmp_path, DEPLOY_DATABASE="bundled")).secrets_problems()
    assert any("must reach host `postgres`" in p for p in problems), problems


# -- go-live preconditions (07/O4) ---------------------------------------------------------------------------------
def test_go_live_passes_when_every_precondition_holds(
    d: ModuleType, fake: FakeHost, github: type[GitHub], tmp_path: Path
) -> None:
    running(fake)
    checks = d.go_live_checks(d.ComposeHost("production", env_file(tmp_path)), release(d), False)
    assert refused(checks) == [], checks
    assert len(checks) >= 6, "fewer checks ran than the preconditions name"


@pytest.mark.parametrize(
    ("fault", "check"),
    [
        ("red", "CI is green on the exact commit"),
        ("no-ci-run", "CI is green on the exact commit"),
        ("no-token", "CI is green on the exact commit"),
        ("missing-image", "the images exist"),
        ("private-jwks", "the configuration is safe to serve (config-check in the image)"),
        ("no-secret", "required settings and secrets are in place"),
        ("no-rollback", "the rollback path is known"),
    ],
)
def test_go_live_refuses_each_missing_precondition(
    d: ModuleType, fake: FakeHost, github: type[GitHub], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    fault: str, check: str,
) -> None:  # fmt: skip
    running(fake)
    path = env_file(tmp_path)
    target = release(d)
    if fault == "red":
        github.gate = "failure"
    elif fault == "no-ci-run":
        github.gate = ""
    elif fault == "no-token":
        monkeypatch.delenv("GH_TOKEN")
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    elif fault == "missing-image":
        del fake.pullable[API_B]
    elif fault == "private-jwks":  # what config/production.py says, run inside the image (never duplicated here)
        fake.config_problems = ["APP_AUTH_JWKS_FILE holds a private key: the API verifies, it never mints"]
    elif fault == "no-secret":
        path = env_file(tmp_path, APP_DATABASE_URL="")
    elif fault == "no-rollback":
        fake.labels = None
    checks = d.go_live_checks(d.ComposeHost("production", path), target, False)
    assert refused(checks) == [check], checks


def test_the_first_release_has_no_rollback_only_when_said_so(
    d: ModuleType, fake: FakeHost, github: type[GitHub], tmp_path: Path
) -> None:
    checks = d.go_live_checks(d.ComposeHost("production", env_file(tmp_path)), release(d), True)
    assert refused(checks) == []


def test_in_github_actions_production_must_wait_for_a_person(
    d: ModuleType, fake: FakeHost, github: type[GitHub], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    running(fake)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    host = d.ComposeHost("production", env_file(tmp_path))
    assert refused(d.go_live_checks(host, release(d), False)) == []
    github.reviewers = False
    assert refused(d.go_live_checks(host, release(d), False)) == ["a person approves production"]


def test_staging_does_not_ask_github(d: ModuleType, fake: FakeHost, tmp_path: Path) -> None:
    checks = d.go_live_checks(d.ComposeHost("staging", env_file(tmp_path, APP_ENV="staging")), release(d), False)
    assert refused(checks) == [] and not any("CI" in str(c["check"]) for c in checks), checks


# -- deploy, revert, rollback (07/O2, O5, O6) -----------------------------------------------------------------------
def test_a_deploy_migrates_before_it_starts_the_new_version_and_records_it(
    d: ModuleType, fake: FakeHost, github: type[GitHub], tmp_path: Path
) -> None:
    running(fake)
    code, result = d.deploy(d.ComposeHost("production", env_file(tmp_path)), release(d), False, True)
    assert code == 0 and result["result"] == "deployed" and result["migration"] == "0002", result
    steps = [" ".join(c) for c in fake.changes()]
    migrate = next(i for i, s in enumerate(steps) if s.endswith(" migrate"))
    up = next(i for i, s in enumerate(steps) if " up " in s)
    assert migrate < up, "migrations run before the new version takes traffic (07/O2)"
    assert fake.labels and fake.labels["api-image"] == API_B and fake.labels["previous-api-image"] == API_A
    history = (tmp_path / "history" / "history.jsonl").read_text().splitlines()
    entry = json.loads(history[-1])
    assert (entry["sha"], entry["migration"], entry["action"]) == (SHA_B, "0002", "deploy")
    assert entry["by"] and entry["at"], "who and when (07/O3)"


def test_a_release_that_fails_smoke_is_reverted_to_the_previous_digest(
    d: ModuleType, fake: FakeHost, github: type[GitHub], tmp_path: Path
) -> None:
    running(fake)
    fake.smoke_ok[SHA_B] = False
    code, result = d.deploy(d.ComposeHost("production", env_file(tmp_path)), release(d), False, True)
    assert code == 1 and result["result"] == "reverted", result
    assert fake.labels and fake.labels["api-image"] == API_A and fake.db_revision == "0001", fake.labels
    assert "downgrade: 0002 -> 0001" in str(result["revert"]), "the schema went back one step before N restarted"


def test_redeploying_the_running_release_changes_nothing(d: ModuleType, fake: FakeHost, tmp_path: Path) -> None:
    running(fake)
    host = d.ComposeHost("staging", env_file(tmp_path, APP_ENV="staging"))
    code, result = d.deploy(host, release(d, API_A, WEB_A), False, True)
    assert code == 0 and result["changed"] is False
    assert all("smoke.py" in " ".join(c) for c in fake.changes()), fake.changes()


def test_a_dry_run_prints_the_plan_and_changes_nothing(
    d: ModuleType, fake: FakeHost, github: type[GitHub], tmp_path: Path
) -> None:
    running(fake)
    host = d.ComposeHost("production", env_file(tmp_path), dry_run=True)
    code, _ = d.deploy(host, release(d), False, True)
    assert code == 0 and fake.changes() == [], fake.changes()
    assert any(p.endswith(" migrate") for p in host.plan) and any(" up " in p for p in host.plan), host.plan
    assert not (tmp_path / "history").exists(), "a dry run records nothing"


def test_a_rollback_steps_the_schema_down_with_the_newer_image_first(
    d: ModuleType, fake: FakeHost, tmp_path: Path
) -> None:
    running(fake, API_B, WEB_B, SHA_B)
    fake.labels = {**(fake.labels or {}), "previous-api-image": API_A, "previous-web-image": WEB_A if WEB else "none"}
    host = d.ComposeHost("staging", env_file(tmp_path, APP_ENV="staging"))
    code, result = d.rollback(host, d.Release(API_A))
    assert code == 0 and result["result"] == "rolled back" and fake.db_revision == "0001", result
    downgrade = next(c for c in fake.calls if "downgrade" in c)
    assert downgrade[downgrade.index("--to") + 1] == "0001"
    assert fake.labels and fake.labels["api-image"] == API_A and fake.labels["web-image"] == (WEB_A if WEB else "none")


def test_a_rollback_with_nothing_running_is_refused(d: ModuleType, fake: FakeHost, tmp_path: Path) -> None:
    with pytest.raises(d.Refused, match="nothing is running"):
        d.rollback(d.ComposeHost("staging", env_file(tmp_path, APP_ENV="staging")), d.Release(API_A))


def test_restarting_old_code_on_a_newer_schema_is_never_healthy(d: ModuleType, fake: FakeHost, tmp_path: Path) -> None:
    """The 07 §5 replay: N's image on N+1's schema. /ready (the healthcheck) compares the revision with the head."""
    running(fake, API_B, WEB_B, SHA_B)
    host = d.ComposeHost("staging", env_file(tmp_path, APP_ENV="staging"))
    assert host.up(d.Release(API_A, WEB_A if WEB else None, SHA_A, "0001"), None) is False


# -- the target's compose file --------------------------------------------------------------------------------------
def test_the_compose_file_runs_built_images_by_digest_and_never_builds() -> None:
    text = (ROOT / "ops" / "deploy" / "compose-host" / "compose.yaml").read_text()
    assert "build:" not in text, "a deploy target never builds: it runs the image CI built (07/O1)"
    images = [line.split("image:", 1)[1].strip() for line in text.splitlines() if line.strip().startswith("image:")]
    assert images and all(i.startswith("${") or "@sha256:" in i for i in images), images
    local = (ROOT / "compose.yaml").read_text()
    pinned = [i for i in images if "@sha256:" in i]
    assert pinned and all(i in local for i in pinned), "the bundled Postgres is the local stack's pin (one home)"
    assert "stop_grace_period: 2m" in text, "the worker drains the job in hand before it is killed (07/O6)"


@pytest.mark.skipif(shutil.which("docker") is None, reason="needs the docker CLI (not a daemon)")
def test_the_compose_file_resolves_with_the_example_env_file(tmp_path: Path) -> None:
    example = (ROOT / "ops" / "deploy" / "compose-host" / "host.env.example").read_text()
    filled = "".join(f"{line}x{'x' * 31}\n" if line.endswith("=") else f"{line}\n" for line in example.splitlines())
    path = tmp_path / "example.env"
    path.write_text(filled)
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "APP_ENV": "staging", "API_IMAGE": API_A,
           "WEB_IMAGE": WEB_A}  # fmt: skip
    compose = ROOT / "ops" / "deploy" / "compose-host" / "compose.yaml"
    argv = ["docker", "compose", "-f", str(compose), "-p", "check", "--env-file", str(path), "--profile", "ops"]
    argv += ["config", "--format", "json"]
    result = subprocess.run(argv, capture_output=True, text=True, env=env, check=False)  # noqa: S603
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    assert services["api"]["image"] == API_A and "migrate" in services
    assert "APP_MIGRATION_DATABASE_URL" not in services["api"]["environment"], "the API never holds the owner's URL"
    assert "APP_DATABASE_URL" not in services["migrate"]["environment"]
    del env["API_IMAGE"]
    missing = subprocess.run(argv, capture_output=True, text=True, env=env, check=False)  # noqa: S603
    assert missing.returncode != 0 and "API image digest" in missing.stderr, "no image, no deploy"
