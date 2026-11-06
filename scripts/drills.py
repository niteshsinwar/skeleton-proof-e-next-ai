#!/usr/bin/env python3
"""Rehearse a rollback and a restore on local Docker, through the same deploy code as production (07/O5, O20).

  make rehearse-rollback   # deploy N, migrate, deploy N+1, roll back one migration step at a time to N (07/O5)
  make restore-drill       # dump, restore to a scratch database, prove /ready and the data and the audit chain (07/O20)

Each builds this commit's images, pushes them to a throwaway local registry so they are named by digest as in
production, and deploys them with scripts/deploy.py to a throwaway Compose project on the bundled database. Every
step prints what it proved; the first failure stops the drill with exit 1. Everything it made is removed at the end.
Run from apps/api with its environment (the Makefile does): it signs test tokens with a throwaway key.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deploy  # noqa: E402  (the deploy script beside this one: the same code a real deploy runs)

from skeleton_proof_e_next_ai.config.project import DEFAULT_TENANT, MULTI_TENANT  # noqa: E402

ROOT = deploy.ROOT
REHEARSAL = ROOT / "ops" / "deploy" / "compose-host" / "compose.rehearsal.yaml"
PKG = "skeleton_proof_e_next_ai"
ISSUER, AUDIENCE = "https://issuer.rehearsal.invalid", "app-api"
TENANT = "00000000-0000-0000-0000-0000000000d1" if MULTI_TENANT else str(DEFAULT_TENANT)
# Fixed, well-formed SHAs per version, so repeated drills reuse Docker's build cache.
SHA_N, SHA_N1, SHA_BAD = (hashlib.sha1(f"{PKG}-{v}".encode()).hexdigest() for v in ("N", "N+1", "bad"))  # noqa: S324
REHEARSAL_REVISION = "rehearsal_0002"


class DrillFailed(Exception):
    pass


def say(message: str) -> None:
    print(f"drill: {message}", flush=True)


def expect(condition: object, message: str) -> None:
    if not condition:
        raise DrillFailed(message)
    say(f"proved  {message}")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def docker(*args: str, stdin: str | None = None) -> str:
    result = deploy.run(["docker", *args], env=None, stdin=stdin)
    if result.returncode != 0:
        raise DrillFailed(f"docker {' '.join(args[:3])} failed:\n{result.stderr[-2000:]}")
    return result.stdout


def http(method: str, url: str, token: str | None = None, body: object = None) -> tuple[int, dict[str, object]]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers |= {"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4())}
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers=headers)  # noqa: S310 (a local URL)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


class Drill:
    """A registry, a host env file, a config folder and a Compose project, all throwaway."""

    def __init__(self, name: str) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix=f"{name}-"))
        self.registry_project = f"{deploy.SLUG}-{name}-registry"
        self.key = Ed25519PrivateKey.generate()
        self.api_port, self.web_port = free_port(), free_port()
        self.env_file = self.tmp / "staging.env"
        self.config = self.tmp / "config"
        self.config.mkdir(mode=0o755)
        os.environ["DEPLOY_STATE_DIR"] = str(self.tmp / "history")
        self.project_name = name
        self.tags: list[str] = []

    # -- set up ---------------------------------------------------------------------------------------------------
    def start_registry(self) -> str:
        os.environ["REGISTRY_PORT"] = str(free_port())
        docker("compose", "-f", str(REHEARSAL), "-p", self.registry_project, "up", "-d", "--wait")
        registry = f"127.0.0.1:{os.environ['REGISTRY_PORT']}"
        say(f"registry at {registry}")
        return registry

    def write_settings(self, private_jwks: bool = False) -> None:
        public = json.loads(jwt.algorithms.OKPAlgorithm.to_jwk(self.key.public_key()))
        jwk = {**public, "kid": "drill-1", "alg": "EdDSA", "use": "sig"}
        if private_jwks:  # the planted go-live fault: a JWKS that holds the signing key itself (07/O4)
            jwk = {**json.loads(jwt.algorithms.OKPAlgorithm.to_jwk(self.key)), "kid": "drill-1", "alg": "EdDSA"}
        (self.config / "jwks.json").write_text(json.dumps({"keys": [jwk]}))
        (self.config / "jwks.json").chmod(0o644)

        def pw() -> str:
            return secrets.token_hex(16)

        values = {
            "DEPLOY_DATABASE": "bundled",
            "DEPLOY_BASE_URL": f"http://127.0.0.1:{self.api_port}",
            "API_PORT": str(self.api_port),
            "BIND_ADDRESS": "127.0.0.1",
            "APP_MIGRATION_DATABASE_URL": f"postgresql+psycopg://app_owner:{pw()}@postgres:5432/app",
            "APP_DATABASE_URL": f"postgresql+psycopg://app_runtime:{pw()}@postgres:5432/app",
            "APP_CONFIG_DIR": str(self.config),
            "APP_AUTH_ISSUER": ISSUER,
            "APP_AUTH_AUDIENCE": AUDIENCE,
            "APP_MCP_SECRETS_KEY": base64.b64encode(secrets.token_bytes(32)).decode(),
            "APP_MCP_RESOURCE_URL": "https://api.rehearsal.invalid/mcp",
            "APP_MCP_ALLOWED_HOSTS": '["api.rehearsal.invalid"]',
            "DEPLOY_WEB_URL": f"http://127.0.0.1:{self.web_port}",
            "WEB_PORT": str(self.web_port),
            "SESSION_SECRET": pw() + pw(),
            "APP_BASE_URL": f"http://127.0.0.1:{self.web_port}",
            "OIDC_ISSUER": ISSUER,
            "OIDC_CLIENT_ID": "web",
            "OIDC_CLIENT_SECRET": pw(),
        }
        if self.env_file.exists():  # keep the passwords the database was created with
            values |= {k: v for k, v in deploy.read_env_file(self.env_file).items() if "DATABASE_URL" in k}
        self.env_file.write_text("".join(f"{k}={v}\n" for k, v in values.items()))
        self.env_file.chmod(0o600)

    def host(self) -> deploy.ComposeHost:
        host = deploy.ComposeHost("staging", self.env_file)
        host.project = f"{deploy.SLUG}-{self.project_name}"  # never the real staging project on this machine
        return host

    def publish(self, registry: str) -> deploy.Release:
        images = deploy.publish(registry, SHA_N, dry_run=False)
        self.tags += [ref.split("@", 1)[0] + f":{SHA_N}" for ref in images.values()]
        say(f"published N: {images}")
        return deploy.Release(images["api"], images.get("web"))

    def derive(self, registry: str, base: str, sha: str, migration: str | None = None, baked: str | None = None) -> str:
        """A later version built FROM version N: one more migration, or (the planted bad build) a revision label that
        the build doesn't show on /health."""
        folder = self.tmp / f"build-{sha[:8]}"
        folder.mkdir()
        lines = [f"FROM {base}"]
        if migration:
            (folder / f"{REHEARSAL_REVISION}.py").write_text(migration)
            lines.append(f"COPY {REHEARSAL_REVISION}.py /app/apps/api/src/{PKG}/persistence/migrations/versions/")
        lines += [f"ENV APP_BUILD_SHA={baked or sha}", f"LABEL org.opencontainers.image.revision={sha}"]
        (folder / "Dockerfile").write_text("\n".join(lines) + "\n")
        repo = base.split("@", 1)[0]
        docker("build", "-q", "-t", f"{repo}:{sha}", str(folder))
        self.tags.append(f"{repo}:{sha}")
        docker("push", "-q", f"{repo}:{sha}")
        digests = json.loads(docker("image", "inspect", f"{repo}:{sha}"))[0]["RepoDigests"]
        return next(d for d in digests if d.startswith(f"{repo}@sha256:"))

    # -- the data, through the deployed API and the database ---------------------------------------------------------
    def owner_sql(self, host: deploy.ComposeHost, sql: str, database: str | None = None) -> str:
        env = host._environ(None)
        result = host.compose("exec", "-T", "postgres", "psql", "-qAt", "-v", "ON_ERROR_STOP=1", "-U",
                              env["BUNDLED_DB_USER"], "-d", database or env["BUNDLED_DB_NAME"], stdin=sql)  # fmt: skip
        if result.returncode != 0:
            raise DrillFailed(f"psql failed: {result.stderr[-1000:]}")
        return result.stdout.strip()

    def token(self, host: deploy.ComposeHost) -> str:
        self.owner_sql(host, f"INSERT INTO app.role_grants (tenant_id, subject, role, granted_by, granted_at) "
                             f"VALUES ('{TENANT}', 'drill', 'member', 'drill', now()) ON CONFLICT DO NOTHING;")  # fmt: skip
        now = int(time.time())
        claims = {"iss": ISSUER, "aud": AUDIENCE, "sub": "drill", "tid": TENANT, "iat": now, "exp": now + 900,
                  "amr": ["pwd"], "auth_time": now}  # fmt: skip
        return jwt.encode(claims, self.key, algorithm="EdDSA", headers={"kid": "drill-1"})

    def api(self) -> str:
        return f"http://127.0.0.1:{self.api_port}{deploy_prefix()}"

    def write_items(self, host: deploy.ComposeHost, *titles: str) -> None:
        token = self.token(host)
        for title in titles:
            status, body = http("POST", f"{self.api()}/work-items", token, {"title": title})
            expect(status == 201, f"the deployed API stored {title!r} (status {status}{'' if status == 201 else body})")

    def titles(self, host: deploy.ComposeHost, database: str | None = None) -> list[str]:
        sql = "SELECT title FROM app.work_items ORDER BY title;"
        return [t for t in self.owner_sql(host, sql, database).splitlines() if t]

    # -- tear down ----------------------------------------------------------------------------------------------------
    def close(self, host: deploy.ComposeHost | None) -> None:
        if host is not None:
            host.compose("down", "-v", "--remove-orphans")
        deploy.run(["docker", "compose", "-f", str(REHEARSAL), "-p", self.registry_project, "down", "-v"])
        if self.tags:  # the registry's copies are gone with it; the local tags name a port that no longer exists
            deploy.run(["docker", "image", "rm", *self.tags])
        for path in sorted(self.tmp.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        self.tmp.rmdir()


def scratch(url: str) -> str:
    """The same server and role, the scratch database instead of the live one."""
    return url.rsplit("/", 1)[0] + "/restore_drill"


def deploy_prefix() -> str:
    return ""


def run_deploy(host: deploy.ComposeHost, release: deploy.Release) -> tuple[int, dict[str, object]]:
    code, result = deploy.deploy(host, deploy.Release(release.api_image, release.web_image), False, revert=True)
    outcome = result.get("result") or result.get("refused") or ("unchanged" if result.get("changed") is False else "")
    say(f"deploy {release.api_image.rsplit('@', 1)[1][:19]}: exit {code}, {outcome}")
    return code, result


def health(drill: Drill) -> tuple[int, dict[str, object], int, dict[str, object]]:
    hs, hb = http("GET", f"{drill.api()}/health")
    rs, rb = http("GET", f"{drill.api()}/ready")
    return hs, hb, rs, rb


def rehearse_rollback() -> None:
    """07/O5: N -> N+1 -> back to N, one migration step at a time; the half-migrated replay (07 §5) is shown failing."""
    drill, host = Drill("rehearsal"), None
    try:
        registry = drill.start_registry()
        n = drill.publish(registry)
        head_n = docker("run", "--rm", "-e", "APP_ENV=staging", n.api_image, "revision").strip()
        migration = (
            f'"""Rehearsal only (scripts/drills.py): one expand step for the rollback to reverse."""\n\n'
            f"from alembic import op\n\nrevision = \"{REHEARSAL_REVISION}\"\ndown_revision = \"{head_n}\"\n\n\n"
            "def upgrade() -> None:\n    op.execute(\"ALTER TABLE app.work_items ADD COLUMN rehearsal_note text\")\n\n\n"
            "def downgrade() -> None:\n    op.execute(\"ALTER TABLE app.work_items DROP COLUMN rehearsal_note\")\n"
        )
        n1 = deploy.Release(drill.derive(registry, n.api_image, SHA_N1, migration=migration), n.web_image)
        bad = deploy.Release(drill.derive(registry, n.api_image, SHA_BAD, baked=SHA_N), n.web_image)

        drill.write_settings(private_jwks=True)
        host = drill.host()
        code, result = run_deploy(host, n)
        refused = json.dumps(result.get("refused", ""))
        expect(code == 1 and "private key" in refused, "go-live refuses a JWKS holding a private key (07/O4)")
        expect(host.running()[0] is None, "the refused deploy changed nothing: no release is running")

        drill.write_settings()
        code, result = run_deploy(host, n)
        expect(code == 0 and result["migration"] == head_n, f"version N deployed and migrated to {head_n}")
        drill.write_items(host, "a: written under N", "b: written under N")

        code, result = run_deploy(host, n1)
        hs, hb, rs, _ = health(drill)
        expect(code == 0 and result["migration"] == REHEARSAL_REVISION, f"N+1 deployed and migrated to {REHEARSAL_REVISION}")
        expect(hs == 200 and hb.get("sha") == SHA_N1 and rs == 200, "N+1 serves: /health shows its SHA, /ready is 200")
        drill.write_items(host, "c: written under N+1")

        say("replay (07 §5): restart N's code without reversing the migration")
        current, _, _ = host.running()
        assert current is not None
        naive_ok = host.up(deploy.Release(n.api_image, n.web_image, SHA_N, head_n), current)
        _, _, rs, rb = health(drill)
        trap = json.dumps(rb.get("checks", {}))
        expect(not naive_ok and rs == 503 and f"database at {REHEARSAL_REVISION}, code expects {head_n}" in trap,
               f"the half-migrated rollback is caught: /ready 503, {trap}")  # fmt: skip
        code, result = run_deploy(host, n1)
        expect(code == 0, "recovered by redeploying N+1, the image that knows the way down")

        code, result = deploy.rollback(host, deploy.Release(n.api_image))
        say(f"rollback: exit {code}, {result.get('result')}; {result.get('downgrade')}")
        hs, hb, rs, rb = health(drill)
        expect(code == 0 and f"{REHEARSAL_REVISION} -> {head_n}" in str(result.get("downgrade")),
               f"rolled back one migration step at a time: {REHEARSAL_REVISION} -> {head_n}")  # fmt: skip
        expect(hs == 200 and hb.get("sha") == SHA_N and rs == 200, "N serves again: /health shows N's SHA, /ready 200")
        titles = drill.titles(host)
        expect(titles == ["a: written under N", "b: written under N", "c: written under N+1"],
               f"no row was lost across N -> N+1 -> N: {titles}")  # fmt: skip

        code, result = run_deploy(host, bad)
        hs, hb, rs, _ = health(drill)
        now_running = host.running()[0]
        expect(code == 1 and result.get("result") == "reverted" and now_running is not None
               and now_running.api_image == n.api_image and hb.get("sha") == SHA_N,
               "a release that fails smoke is reverted automatically to the previous digest (07/O6)")  # fmt: skip

        code, result = run_deploy(host, n)
        expect(code == 0 and result.get("changed") is False, "deploying the running release again changes nothing")
        say("rehearse-rollback: PASS")
    finally:
        drill.close(host)


def restore_drill() -> None:
    """07/O20, 02/D15: a backup is only a backup once it has been restored and the app has served from it."""
    drill, host = Drill("restore-drill"), None
    try:
        registry = drill.start_registry()
        n = drill.publish(registry)
        drill.write_settings()
        host = drill.host()
        code, _ = run_deploy(host, n)
        expect(code == 0, "deployed version N on the bundled database")
        drill.write_items(host, "a: before the backup", "b: before the backup")
        source = drill.titles(host)
        env = host._environ(None)
        owner = ["-U", env["BUNDLED_DB_USER"]]
        started = time.monotonic()
        for argv in (["pg_dump", *owner, "-d", env["BUNDLED_DB_NAME"], "-Fc", "-f", "/tmp/drill.dump"],
                     ["dropdb", *owner, "--if-exists", "restore_drill"], ["createdb", *owner, "restore_drill"],
                     ["pg_restore", *owner, "-d", "restore_drill", "--exit-on-error", "/tmp/drill.dump"]):  # fmt: skip
            result = host.compose("exec", "-T", "postgres", *argv)
            if result.returncode != 0:
                raise DrillFailed(f"{argv[0]} failed: {result.stderr[-1500:]}")
        took = time.monotonic() - started
        expect(drill.titles(host, "restore_drill") == source, f"the scratch database holds the same rows: {source}")
        port = free_port()
        url = scratch(deploy.read_env_file(drill.env_file)["APP_DATABASE_URL"])
        container = host.compose("run", "-d", "--no-deps", "-p", f"127.0.0.1:{port}:8000", "-e",
                                 f"APP_DATABASE_URL={url}", "api", release=n).stdout.strip()  # fmt: skip
        try:
            status, body = 0, {}
            for _ in range(60):
                try:
                    status, body = http("GET", f"http://127.0.0.1:{port}{deploy_prefix()}/ready")
                except (urllib.error.URLError, ConnectionError):
                    status = 0
                if status == 200:
                    break
                time.sleep(1)
            expect(status == 200, f"the API serves from the restored database: /ready 200 ({body.get('checks', body)})")
            drill.write_items(host, "c: after the backup")  # in the live database only
            status, page = http("GET", f"http://127.0.0.1:{port}{deploy_prefix()}/work-items", drill.token(host))
            served = sorted(str(i.get("title")) for i in page.get("items", []) if isinstance(i, dict))  # type: ignore[union-attr]
            expect(status == 200 and served == source,
                   f"the API reads the restored rows, not the live ones: {served}")  # fmt: skip
        finally:
            docker("rm", "-f", container.splitlines()[-1])
        owner_url = scratch(deploy.read_env_file(drill.env_file)["APP_MIGRATION_DATABASE_URL"])
        verify = host.compose(
            "run", "--rm", "--no-deps", "-T", "--entrypoint", "python",
            "-v", f"{ROOT / 'scripts' / 'verify_audit_chain.py'}:/tmp/verify_audit_chain.py:ro",
            "-e", f"APP_DATABASE_URL={owner_url}", "api", "/tmp/verify_audit_chain.py",
            release=n,
        )  # fmt: skip
        say(verify.stdout.strip())
        examined = [int(w) for w in verify.stdout.split() if w.isdigit()]
        expect(verify.returncode == 0 and examined and examined[0] > 0,
               "the restored audit hash chain verifies, row by row (02/D6, D15)")  # fmt: skip
        say(f"restore took {took:.1f}s for this data set: compare with the RTO this tier states (07/O20)")
        say("restore-drill: PASS")
    finally:
        drill.close(host)


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("drill", choices=["rehearse-rollback", "restore-drill"])
    args = parser.parse_args()
    if deploy.run(["docker", "info"]).returncode != 0:
        print("drill: no Docker daemon answers; the drills run on local Docker", file=sys.stderr)
        return 2
    try:
        rehearse_rollback() if args.drill == "rehearse-rollback" else restore_drill()
    except (DrillFailed, deploy.Refused, RuntimeError) as failure:
        print(f"drill: FAIL  {failure}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
