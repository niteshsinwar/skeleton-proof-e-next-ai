#!/usr/bin/env python3
"""Deploy, migrate, inspect and roll back the BUILT images (07/O1-O6): the deploy contract and its Docker host adapter.

  python3 -I scripts/deploy.py publish       --registry ghcr.io/OWNER --sha SHA    # build once, push, print digests
  python3 -I scripts/deploy.py go-live-check --env production --api-image REF --web-image REF
  python3 -I scripts/deploy.py deploy        --env staging --api-image REF --web-image REF
  python3 -I scripts/deploy.py migrate       --env staging --api-image REF
  python3 -I scripts/deploy.py status        --env staging
  python3 -I scripts/deploy.py rollback      --env staging --to REF [--web-to REF]
  python3 -I scripts/deploy.py ci-status     --sha SHA

The contract every target adapter implements (ops/deploy/README.md): `deploy`, `migrate`, `status`, `rollback --to`,
optionally `shift --percent` for a canary. Each prints ONE JSON document on stdout and its steps on stderr, exits 0
only on success, is idempotent (the release already running is left alone) and has `--dry-run`, which prints the
plan and touches nothing. This file builds one adapter, `compose-host`: a Docker host running
ops/deploy/compose-host/compose.yaml, reached through the Docker CLI (locally, or `DOCKER_HOST=ssh://...`).

An image is named by digest, `REPOSITORY@sha256:<64 hex>` (a bare `sha256:...` takes its repository from
DEPLOY_API_REPOSITORY / DEPLOY_WEB_REPOSITORY in the env file). Settings come from the host env file (--env-file or
DEPLOY_ENV_FILE, default /etc/skeleton-proof-e-next-ai/<env>.env), never from git and never from this shell: Compose lets
the shell override an env file, so only the Docker client's own variables pass through.
Stdlib only, so it runs on a bare CI runner or the host itself.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "ops" / "deploy" / "compose-host" / "compose.yaml"
SMOKE = ROOT / "tests" / "smoke" / "smoke.py"
SLUG = "skeleton-proof-e-next-ai"
TIER = "E"
WEB_IMAGE = True  # Next.js ships its own image; a Vite app is served by the API's
ENVIRONMENTS = ("staging", "production")
DIGEST = re.compile(r"^[a-z0-9][a-z0-9._/:-]*@sha256:[0-9a-f]{64}$")
BARE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
ROLE_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
# The Docker client's own settings are the only variables taken from this shell (Compose lets the shell win).
PASS_THROUGH = ("PATH", "HOME", "USER", "SSH_AUTH_SOCK", "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG",
                "DOCKER_CERT_PATH", "DOCKER_TLS_VERIFY", "TMPDIR")  # fmt: skip
# Login roles the bundled database gets, from the URL that names each (02/Z10: never the owner).
LOGINS = {"APP_DATABASE_URL": ("app_user", "app_worker",)}
WAIT_SECONDS = 240


class Refused(Exception):
    """A precondition failed: nothing was changed."""


@dataclass
class Release:
    api_image: str
    web_image: str | None = None
    sha: str | None = None
    migration: str | None = None


def log(message: str) -> None:
    print(f"deploy: {message}", file=sys.stderr, flush=True)


def run(argv: list[str], env: dict[str, str] | None = None, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    """The one place a command runs (tests replace it). The argv never holds a secret; secrets travel in the env file
    or on stdin."""
    log("$ " + " ".join(argv))
    return subprocess.run(argv, env=env, input=stdin, capture_output=True, text=True, check=False)  # noqa: S603


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def required_names() -> list[str]:
    """Every `${NAME:?...}` the compose file demands, minus the ones this script sets: one home for the list."""
    names = set(re.findall(r"\$\{([A-Z0-9_]+):\?", COMPOSE.read_text(encoding="utf-8")))
    return sorted(names - {"API_IMAGE", "WEB_IMAGE", "APP_ENV"})


def image_ref(value: str | None, repository: str | None, what: str) -> str:
    if not value:
        raise Refused(f"no {what} digest: deploy the image CI built for the commit, by digest (07/O1, O4)")
    if BARE_DIGEST.match(value) and repository:
        value = f"{repository}@{value}"
    if not DIGEST.match(value):
        raise Refused(f"{what} {value!r} is not REPOSITORY@sha256:<digest>: a tag can move, a digest can't (07/O1)")
    return value


def _url_host(url: str) -> str:
    return (urlsplit(url.replace("postgresql+psycopg://", "postgresql://")).hostname or "").lower()


class ComposeHost:
    """The Docker host target: one Compose project per environment, `<slug>-<env>`."""

    def __init__(self, env: str, env_file: Path, dry_run: bool = False) -> None:
        self.env, self.env_file, self.dry_run = env, env_file, dry_run
        self.project = f"{SLUG}-{env}"
        self.plan: list[str] = []
        self.values = self._checked_env_file()
        self.bundled = self.values.get("DEPLOY_DATABASE") == "bundled"

    # -- preconditions on the env file (07/O1, O4) -----------------------------------------------------------------
    def _checked_env_file(self) -> dict[str, str]:
        path = self.env_file.resolve()
        if not path.is_file():
            raise Refused(f"no env file at {path}: write it on the host (ops/deploy/compose-host/host.env.example)")
        if path.is_relative_to(ROOT):
            raise Refused(f"the env file {path} is inside the repository: secrets never travel with the code (07/O1)")
        if path.stat().st_mode & 0o077:
            raise Refused(f"the env file {path} is readable by other users: chmod 600 it")
        values = read_env_file(path)
        if values.get("APP_ENV", self.env) != self.env:
            raise Refused(f"the env file says APP_ENV={values['APP_ENV']} but this deploys {self.env}: wrong file?")
        return values

    def secrets_problems(self) -> list[str]:
        """Required settings that are absent or empty (07/O4); names only, never values."""
        needed = [*required_names(), "DEPLOY_BASE_URL", "DEPLOY_DATABASE"]
        if WEB_IMAGE:
            needed.append("DEPLOY_WEB_URL")
        found = [f"{name} is not set in the env file" for name in needed if not self.values.get(name)]
        database = self.values.get("DEPLOY_DATABASE")
        if database not in (None, "", "managed", "bundled"):
            found.append(f"DEPLOY_DATABASE is {database!r}: managed or bundled")
        owner = urlsplit(self.values.get("APP_MIGRATION_DATABASE_URL", "")).username
        for name in LOGINS:
            url = self.values.get(name, "")
            if url and urlsplit(url).username == owner:
                found.append(f"{name} connects as the schema owner: the app gets its own login role (02/Z10)")
            if url and self.bundled and _url_host(url) != "postgres":
                found.append(f"{name} must reach host `postgres` with DEPLOY_DATABASE=bundled")
        return found

    # -- the Docker CLI ------------------------------------------------------------------------------------------
    def _environ(self, release: Release | None, previous: Release | None = None) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k in PASS_THROUGH}
        env["APP_ENV"] = self.env
        env["API_IMAGE"] = release.api_image if release else "none"
        if WEB_IMAGE:
            env["WEB_IMAGE"] = (release.web_image if release else None) or "none"
        if release:
            env |= {"RELEASE_SHA": release.sha or "unknown", "RELEASE_MIGRATION": release.migration or "unknown",
                    "RELEASE_BY": actor(), "RELEASE_AT": now()}  # fmt: skip
        if previous:
            env |= {"PREVIOUS_API_IMAGE": previous.api_image, "PREVIOUS_WEB_IMAGE": previous.web_image or "none"}
        if self.bundled:  # the owner's credentials are written once, in APP_MIGRATION_DATABASE_URL
            owner = urlsplit(self.values.get("APP_MIGRATION_DATABASE_URL", ""))
            env |= {"BUNDLED_DB_USER": unquote(owner.username or ""), "BUNDLED_DB_PASSWORD": unquote(owner.password or ""),
                    "BUNDLED_DB_NAME": owner.path.lstrip("/") or "app"}  # fmt: skip
        return env

    def docker(self, *args: str, release: Release | None = None, previous: Release | None = None,
               stdin: str | None = None, reads: bool = False) -> subprocess.CompletedProcess[str]:  # fmt: skip
        """A dry run still reads (`ps`, `inspect`), so its plan starts from what really runs; it never changes."""
        argv = ["docker", *args]
        if not reads:
            self.plan.append(" ".join(argv))
            if self.dry_run:
                return subprocess.CompletedProcess(argv, 0, "", "")
        return run(argv, env=self._environ(release, previous), stdin=stdin)

    def compose(self, *args: str, release: Release | None = None, previous: Release | None = None,
                stdin: str | None = None) -> subprocess.CompletedProcess[str]:  # fmt: skip
        base = ["compose", "-f", str(COMPOSE), "-p", self.project, "--env-file", str(self.env_file.resolve())]
        if self.bundled:
            base += ["--profile", "bundled-db"]
        return self.docker(*base, *args, release=release, previous=previous, stdin=stdin)

    # -- the contract --------------------------------------------------------------------------------------------
    def status(self) -> dict[str, object]:
        ids = self.docker("ps", "-a", "-q", "--filter", f"label=com.docker.compose.project={self.project}", reads=True)
        services: dict[str, dict[str, str]] = {}
        labels: dict[str, str] = {}
        if ids.stdout.split():
            for c in json.loads(self.docker("inspect", *ids.stdout.split(), reads=True).stdout or "[]"):
                config_labels = c["Config"].get("Labels") or {}
                service = config_labels.get("com.docker.compose.service", "?")
                state = c.get("State", {})
                services[service] = {"image": c["Config"]["Image"], "state": state.get("Status", "?"),
                                     "health": (state.get("Health") or {}).get("Status", "none")}  # fmt: skip
                if service == "api" and state.get("Status") == "running":
                    prefix = f"{SLUG}.release."
                    labels = {k.removeprefix(prefix): v for k, v in config_labels.items() if k.startswith(prefix)}
        return {"target": "compose-host", "env": self.env, "project": self.project, "services": services,
                "release": labels or None}  # fmt: skip

    def running(self) -> tuple[Release | None, Release | None, bool]:
        """The release serving now, the one before it (from its labels), and whether every service is healthy."""
        found = self.status()
        labels = found["release"]
        if not isinstance(labels, dict):
            return None, None, False
        services = found["services"]
        assert isinstance(services, dict)
        healthy = all(s["state"] == "running" and s["health"] in ("healthy", "none") for s in services.values())
        current = Release(labels["api-image"], _none(labels.get("web-image")), labels.get("sha"), labels.get("migration"))
        before = labels.get("previous-api-image")
        previous = Release(before, _none(labels.get("previous-web-image"))) if _none(before) else None
        return current, previous, healthy

    def pull(self, release: Release) -> None:
        for ref in filter(None, (release.api_image, release.web_image)):
            if self.docker("pull", "-q", ref).returncode != 0:
                raise Refused(f"the image {ref} does not exist or can't be pulled: build and push it first (07/O4)")

    def image_sha(self, ref: str) -> str:
        inspected = json.loads(self.docker("image", "inspect", ref, reads=True).stdout or "[{}]")[0]
        sha = ((inspected.get("Config") or {}).get("Labels") or {}).get("org.opencontainers.image.revision", "")
        if self.dry_run and not sha:
            return "<the image's revision label>"  # not pulled in a dry run
        if not GIT_SHA.match(sha):
            raise Refused(f"{ref} carries no git SHA label: it can't be traced to a commit or smoke-tested (02/A12)")
        return sha

    def image_head(self, ref: str) -> str:
        result = self.docker("run", "--rm", "-e", f"APP_ENV={self.env}", ref, "revision")
        if self.dry_run:
            return "<head of the target image>"
        if result.returncode != 0 or not result.stdout.strip():
            raise Refused(f"{ref} could not name its migration head: {result.stderr.strip()[-300:]}")
        return result.stdout.strip().splitlines()[-1]

    def config_problems(self, release: Release) -> list[str]:
        """The image's own production check, with the real env file and mounts (config/production.py, 07/O4)."""
        result = self.compose("run", "--rm", "--no-deps", "-T", "api", "config-check", release=release)
        if result.returncode == 0:
            return []
        lines = [line.removeprefix("config-check: ") for line in result.stdout.splitlines()]
        return [line for line in lines if "safe to start" not in line and "problem(s)" not in line] or [
            f"config-check failed: {result.stderr.strip()[-500:]}"
        ]

    def migrate(self, release: Release) -> str:
        """Before the new version takes traffic, run by the new image itself (07/O2)."""
        if self.bundled:
            self._check(self.compose("up", "-d", "--wait", "postgres", release=release), "the bundled database")
        result = self._check(self.compose("run", "--rm", "-T", "migrate", release=release), "migrate")
        if self.bundled:
            self.provision(release)
        found = re.search(r"at head (\S+)", result.stdout)
        return found.group(1) if found else ("<head>" if self.dry_run else "unknown")

    def provision(self, release: Release) -> None:
        """Bundled database only: each app login role exists, with the password its URL names (stdin, never argv)."""
        statements = []
        for name, groups in LOGINS.items():
            url = urlsplit(self.values.get(name, ""))
            user, password = unquote(url.username or ""), unquote(url.password or "")
            if not ROLE_NAME.match(user) or not password:
                raise Refused(f"{name} must name a login role (lowercase letters, digits, _) and its password")
            literal = password.replace("'", "''")
            statements += [
                f"DO $$BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{user}') "
                f"THEN CREATE ROLE {user} LOGIN; END IF; END$$;",
                f"ALTER ROLE {user} WITH LOGIN PASSWORD '{literal}';",
                f"GRANT {', '.join(groups)} TO {user};",
            ]
        env = self._environ(release)
        self._check(
            self.compose("exec", "-T", "postgres", "psql", "-q", "-v", "ON_ERROR_STOP=1", "-U", env["BUNDLED_DB_USER"],
                         "-d", env["BUNDLED_DB_NAME"], release=release, stdin="\n".join(statements) + "\n"),
            "provision the app's login roles",
        )  # fmt: skip

    def up(self, release: Release, previous: Release | None) -> bool:
        result = self.compose("up", "-d", "--wait", "--wait-timeout", str(WAIT_SECONDS), "--remove-orphans",
                              release=release, previous=previous)  # fmt: skip
        if result.returncode != 0:
            log(f"up did not become healthy: {result.stderr.strip()[-800:]}")
        return result.returncode == 0

    def smoke(self, release: Release) -> bool:
        argv = [sys.executable, "-I", str(SMOKE), "--base-url", self.values.get("DEPLOY_BASE_URL", "")]
        if WEB_IMAGE:
            argv += ["--web-url", self.values.get("DEPLOY_WEB_URL", "")]
        argv += ["--sha", release.sha or ""]
        self.plan.append(" ".join(argv))
        if self.dry_run:
            return True
        result = run(argv)
        sys.stderr.write(result.stdout + result.stderr)
        return result.returncode == 0

    def downgrade_to(self, current: Release, head: str) -> str:
        """One migration step at a time, by the image now running: only it knows the way down (07/O5)."""
        result = self.compose("run", "--rm", "-T", "migrate", "downgrade", "--to", head, release=current)
        return self._check(result, f"downgrade to {head}").stdout.strip()

    def stop(self) -> None:
        self.compose("stop")

    def _check(self, result: subprocess.CompletedProcess[str], what: str) -> subprocess.CompletedProcess[str]:
        if result.returncode != 0:
            raise RuntimeError(f"{what} failed:\n{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        return result


def _none(value: str | None) -> str | None:
    return None if value in (None, "", "none", "unknown") else value


def actor() -> str:
    return os.environ.get("DEPLOY_ACTOR") or os.environ.get("GITHUB_ACTOR") or f"operator:{getpass.getuser()}"


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def record(entry: dict[str, object], dry_run: bool = False) -> dict[str, object]:
    """Every deploy and rollback is recorded: SHA, migration revision, who and when (07/O3). Appended to
    .deploy/history.jsonl where this runs (gitignored), printed as the command's result, and put into docs/STATE.md
    by /release."""
    entry = {"at": now(), "by": actor(), **entry}
    if dry_run:
        return {**entry, "result": f"dry run: would be {entry.get('result')}"}
    if os.environ.get("GITHUB_RUN_ID"):
        entry["run"] = f"{os.environ.get('GITHUB_SERVER_URL', '')}/{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    folder = Path(os.environ.get("DEPLOY_STATE_DIR", ROOT / ".deploy"))
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "history.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry


# -- GitHub: the gate on the exact commit, and the human approval (07/O3, O4) ------------------------------------------
def github(path: str) -> object:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise Refused("no GH_TOKEN or GITHUB_TOKEN: CI on the exact commit can't be checked, so it isn't assumed")
    base = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    request = urllib.request.Request(f"{base}{path}", headers={  # noqa: S310  (an https API, or a test's stub)
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"})  # fmt: skip
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
            return json.loads(response.read())
    except (urllib.error.URLError, ValueError) as error:
        raise Refused(f"GitHub could not be asked ({path}): {error}") from error


def repository() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not re.match(r"^[\w.-]+/[\w.-]+$", repo):
        raise Refused("GITHUB_REPOSITORY (owner/name) is not set: CI on the exact commit can't be checked")
    return repo


def ci_problem(sha: str) -> str | None:
    """None when the required `gate` check passed on exactly this commit (11/GL3)."""
    if not GIT_SHA.match(sha or ""):
        return f"{sha!r} is not a full commit SHA"
    found = github(f"/repos/{repository()}/commits/{sha}/check-runs?check_name=gate&filter=latest")
    runs = found.get("check_runs", []) if isinstance(found, dict) else []
    conclusions = sorted({str(r.get("conclusion")) for r in runs})
    if conclusions == ["success"]:
        return None
    return f"CI's gate on {sha[:12]} is {', '.join(conclusions) or 'missing'}, not success: deploy only a green commit"


def reviewer_problem(env: str) -> str | None:
    """S and E: production waits for a person (07/O3). Checked where it can be (GitHub Actions); at a terminal, the
    person running it is the human action."""
    if TIER == "P" or env != "production" or os.environ.get("GITHUB_ACTIONS") != "true":
        return None
    found = github(f"/repos/{repository()}/environments/{env}")
    rules = found.get("protection_rules", []) if isinstance(found, dict) else []
    # The REST docs show a reviewer rule by its `reviewers` list; the type name is GitHub's, not confirmed in the docs.
    if any(r.get("type") == "required_reviewers" or r.get("reviewers") for r in rules if isinstance(r, dict)):
        return None
    return "the production environment has no required reviewer: a production deploy is a human decision (07/O3)"


# -- commands ----------------------------------------------------------------------------------------------------------
def go_live_checks(host: ComposeHost, release: Release, first_release: bool) -> list[dict[str, object]]:
    """Every go-live precondition, each reported (07/O4). Refuses unless all pass."""
    checks: list[dict[str, object]] = []

    def check(name: str, problem: str | list[str] | None) -> None:
        problems = [problem] if isinstance(problem, str) else (problem or [])
        checks.append({"check": name, "ok": not problems, "problems": problems})
        log(f"{'pass' if not problems else 'REFUSED'}  {name}" + "".join(f"\n    - {p}" for p in problems))

    def attempt(name: str, probe: object) -> object:
        try:
            return probe() if callable(probe) else probe
        except Refused as refusal:
            check(name, str(refusal))
            return False

    check("required settings and secrets are in place", host.secrets_problems())
    if attempt("the images exist", lambda: host.pull(release)) is not False:
        check("the images exist", None)
        sha = attempt("the image names its commit", lambda: host.image_sha(release.api_image))
        if isinstance(sha, str):
            release.sha = sha
            check("the image names its commit", None)
            if host.env == "production" and host.dry_run:
                checks.append({"check": "CI is green on the exact commit", "ok": True, "skipped": "dry run"})
            elif host.env == "production":
                found = attempt("CI is green on the exact commit", lambda: ci_problem(sha))
                if found is not False:
                    check("CI is green on the exact commit", found if isinstance(found, str) else None)
        check("the configuration is safe to serve (config-check in the image)", host.config_problems(release))
    if host.env == "production":
        current, _, _ = host.running()
        known = current is not None or first_release
        check("the rollback path is known", None if known else
              "nothing is running here to roll back to; pass --first-release only for the very first go-live")  # fmt: skip
        found = None if host.dry_run else attempt("a person approves production", lambda: reviewer_problem(host.env))
        if found is not False:
            check("a person approves production", found if isinstance(found, str) else None)
    return checks


def deploy(host: ComposeHost, release: Release, first_release: bool, revert: bool) -> tuple[int, dict[str, object]]:
    current, _, healthy = host.running()
    if current and current.api_image == release.api_image and current.web_image == release.web_image and healthy:
        log("this release is already running and healthy: nothing to change")
        release.sha, release.migration = current.sha, current.migration
        ok = host.smoke(release)
        return (0 if ok else 1), {"action": "deploy", "changed": False, "smoke": "pass" if ok else "fail", **asdict(release)}
    checks = go_live_checks(host, release, first_release)
    refused = [c for c in checks if not c["ok"]]
    if refused:
        return 1, {"action": "deploy", "changed": False, "refused": refused, "checks": checks}
    release.migration = host.migrate(release)
    healthy_up = host.up(release, current)
    smoked = healthy_up and host.smoke(release)
    entry: dict[str, object] = {"action": "deploy", "env": host.env, **asdict(release),
                                "previous": asdict(current) if current else None}  # fmt: skip
    if smoked:
        return 0, record({**entry, "result": "deployed", "smoke": "pass"}, host.dry_run)
    if not revert:
        return 1, record({**entry, "result": "failed", "smoke": "fail"}, host.dry_run)
    if current is None:
        log("smoke failed and nothing ran before: stopping the new release rather than serving it")
        host.stop()
        return 1, record({**entry, "result": "failed, stopped", "smoke": "fail"}, host.dry_run)
    log(f"smoke failed: reverting automatically to {current.api_image} (07/O6)")
    code, reverted = rollback(host, current)
    return 1, record({**entry, "result": "reverted" if code == 0 else "revert failed", "smoke": "fail",
                      "revert": reverted}, host.dry_run)  # fmt: skip


def rollback(host: ComposeHost, target: Release) -> tuple[int, dict[str, object]]:
    """Back to an older release: the schema steps down one migration at a time to the target's head, by the image now
    running, then the target's images start and are smoke-tested (07/O5). Data that looks wrong is never a rollback."""
    current, previous, healthy = host.running()
    if current is None:
        raise Refused("nothing is running here: there is nothing to roll back")
    if WEB_IMAGE and target.web_image is None:
        if previous and previous.api_image == target.api_image:
            target.web_image = previous.web_image
        else:
            raise Refused("name the web image to return to with --web-to (only the previous release is remembered)")
    if current.api_image == target.api_image and current.web_image == target.web_image and healthy:
        log("the target release is already running and healthy: nothing to change")
        return 0, {"action": "rollback", "changed": False, **asdict(current)}
    host.pull(target)
    target.sha = host.image_sha(target.api_image)
    target.migration = host.image_head(target.api_image)
    steps = host.downgrade_to(current, target.migration)
    healthy_up = host.up(target, current)
    smoked = healthy_up and host.smoke(target)
    entry = {"action": "rollback", "env": host.env, **asdict(target), "from": asdict(current), "downgrade": steps,
             "result": "rolled back" if smoked else "rollback unhealthy", "smoke": "pass" if smoked else "fail"}  # fmt: skip
    return (0 if smoked else 1), record(entry, host.dry_run)


def publish(registry: str, sha: str, dry_run: bool) -> dict[str, str]:
    """Build each image once for this commit, push it, and name it by its registry digest (07/O1)."""
    if not GIT_SHA.match(sha):
        raise Refused(f"{sha!r} is not a full commit SHA")
    images = {"api": "apps/api/Dockerfile"}
    if WEB_IMAGE:
        images["web"] = "apps/web/Dockerfile"
    out: dict[str, str] = {}
    for role, dockerfile in images.items():
        repo = f"{registry.rstrip('/').lower()}/{SLUG}-{role}"
        steps = [
            ["docker", "build", "-f", str(ROOT / dockerfile), "--build-arg", f"BUILD_SHA={sha}", "-t", f"{repo}:{sha}",
             str(ROOT)],
            ["docker", "push", "-q", f"{repo}:{sha}"],
        ]  # fmt: skip
        for argv in steps:
            if dry_run:
                log("(dry run) " + " ".join(argv))
                continue
            result = run(argv)
            if result.returncode != 0:
                raise RuntimeError(f"{' '.join(argv[:2])} failed:\n{result.stderr[-2000:]}")
        if dry_run:
            out[role] = f"{repo}@sha256:<digest>"
            continue
        inspected = json.loads(run(["docker", "image", "inspect", f"{repo}:{sha}"]).stdout or "[{}]")[0]
        digests = [d for d in inspected.get("RepoDigests") or [] if d.startswith(f"{repo}@sha256:")]
        if not digests:
            raise RuntimeError(f"pushed {repo}:{sha} but the registry gave no digest")
        out[role] = digests[0]
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="deploy.py", description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def command(name: str, help_text: str, env: bool = True) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--target", choices=["compose-host"], default="compose-host")
        p.add_argument("--dry-run", action="store_true", help="print the plan; change nothing")
        if env:
            p.add_argument("--env", required=True, choices=ENVIRONMENTS)
            p.add_argument("--env-file", help="the host env file (default: DEPLOY_ENV_FILE or /etc/<slug>/<env>.env)")
        return p

    for name in ("deploy", "go-live-check", "migrate"):
        p = command(name, f"{name} a release")
        p.add_argument("--api-image", required=True, help="REPOSITORY@sha256:... or sha256:...")
        if WEB_IMAGE and name != "migrate":
            p.add_argument("--web-image", help="REPOSITORY@sha256:... or sha256:...")
        p.add_argument("--first-release", action="store_true", help="production's very first go-live: no rollback yet")
        if name == "deploy":
            p.add_argument("--no-revert", action="store_true", help="leave a release that fails smoke in place")
    command("status", "what runs where, and the release record")
    p = command("rollback", "back to an older release")
    p.add_argument("--to", required=True, help="the API image to return to, by digest")
    if WEB_IMAGE:
        p.add_argument("--web-to", help="the web image to return to (default: the previous release's)")
    p = command("publish", "build once and push by digest", env=False)
    p.add_argument("--registry", required=True, help="e.g. ghcr.io/owner")
    p.add_argument("--sha", required=True)
    p.add_argument("--github-output", help="also append api=... (and web=...) to this file")
    p = command("ci-status", "is the required gate green on this commit?", env=False)
    p.add_argument("--sha", required=True)
    args = parser.parse_args(argv)

    try:
        code, result = dispatch(args)
    except Refused as refusal:
        code, result = 1, {"command": args.command, "refused": str(refusal)}
        log(f"REFUSED: {refusal}")
    except RuntimeError as failure:
        code, result = 1, {"command": args.command, "failed": str(failure)}
        log(f"FAILED: {failure}")
    print(json.dumps(result, indent=2, sort_keys=True))
    return code


def dispatch(args: argparse.Namespace) -> tuple[int, dict[str, object]]:
    if args.command == "publish":
        images = publish(args.registry, args.sha, args.dry_run)
        if args.github_output:
            with open(args.github_output, "a", encoding="utf-8") as f:
                f.writelines(f"{role}={ref}\n" for role, ref in images.items())
        return 0, {"command": "publish", "sha": args.sha, **images}
    if args.command == "ci-status":
        problem = ci_problem(args.sha)
        return (1 if problem else 0), {"command": "ci-status", "sha": args.sha, "green": problem is None,
                                       "problem": problem}  # fmt: skip
    env_file = Path(args.env_file or os.environ.get("DEPLOY_ENV_FILE") or f"/etc/{SLUG}/{args.env}.env")
    host = ComposeHost(args.env, env_file, args.dry_run)
    values = host.values
    if args.command == "status":
        return 0, host.status()
    if args.command == "rollback":
        target = Release(image_ref(args.to, values.get("DEPLOY_API_REPOSITORY"), "API image"))
        if WEB_IMAGE and getattr(args, "web_to", None):
            target.web_image = image_ref(args.web_to, values.get("DEPLOY_WEB_REPOSITORY"), "web image")
        code, result = rollback(host, target)
        return code, {**result, "plan": host.plan} if args.dry_run else result
    release = Release(image_ref(args.api_image, values.get("DEPLOY_API_REPOSITORY"), "API image"))
    if WEB_IMAGE and args.command != "migrate":
        release.web_image = image_ref(args.web_image, values.get("DEPLOY_WEB_REPOSITORY"), "web image")
    if args.command == "migrate":
        host.pull(release)
        return 0, {"command": "migrate", "env": host.env, "migration": host.migrate(release), "plan": host.plan}
    if args.command == "go-live-check":
        checks = go_live_checks(host, release, args.first_release)
        ok = all(c["ok"] for c in checks)
        return (0 if ok else 1), {"command": "go-live-check", "env": host.env, "ok": ok, "checks": checks}
    code, result = deploy(host, release, args.first_release, revert=not args.no_revert)
    return code, {**result, "plan": host.plan} if args.dry_run else result


if __name__ == "__main__":
    sys.exit(main())
