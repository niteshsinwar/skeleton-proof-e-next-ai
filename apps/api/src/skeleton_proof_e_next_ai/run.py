"""The one entrypoint a container runs (07/O1: one image, every role).

    python -m skeleton_proof_e_next_ai.run <command>

  api           serve HTTP (the platform's load balancer is in front; the container network is the boundary)
  worker        run the outbox relay, jobs, the reaper; SIGTERM drains it (07/O6)
  migrate       apply migrations to head as the schema owner, before the new version takes traffic (07/O2)
  downgrade     --to REVISION: step the schema down one migration at a time, as the owner, to an older release's head
                (07/O5: never a blind downgrade to base); run by the NEWER image, the only one that knows the way down
  revision      print this image's migration head, so a rollback knows where the schema must stand for it
  config-check  print every reason this configuration must not serve staging or production (07/O4); exit 1 if any

The environment is never assumed (07/O3): APP_ENV must be set, or nothing starts.
"""

from __future__ import annotations

import argparse
import os
import sys

import uvicorn
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.script.revision import RevisionError
from sqlalchemy import create_engine

from .config import production as deployed_config
from .config.settings import API_ROOT, get_settings
from .jobs.__main__ import main as run_worker

COMMANDS = ("api", "worker", "migrate", "downgrade", "revision", "config-check")


def serve(factory: str) -> int:
    uvicorn.run(
        factory,
        factory=True,
        host=os.environ.get("HOST", "0.0.0.0"),  # noqa: S104  (inside a container; the platform's network is the boundary)
        port=int(os.environ.get("PORT", "8000")),
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
        timeout_graceful_shutdown=int(os.environ.get("GRACEFUL_SHUTDOWN_SECONDS", "20")),
        access_log=False,  # the app logs each request itself, as JSON with its correlation id (07/O7)
    )
    return 0


def owner_url() -> str | None:
    """The owner's credential is separate from the app's: the app role never owns a table (02/Z10)."""
    settings = get_settings()
    url = os.environ.get("APP_MIGRATION_DATABASE_URL")
    if not url and settings.env in deployed_config.DEPLOYED:
        return None
    return url or settings.database_url  # local and test connect as the owner already


def alembic_config(url: str | None = None) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    migrations = API_ROOT / "src" / "skeleton_proof_e_next_ai" / "persistence" / "migrations"
    config.set_main_option("script_location", str(migrations))
    if url:
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))  # configparser would read % as interpolation
    return config


def migrate() -> int:
    url = owner_url()
    if url is None:
        print(f"migrate: refusing in {get_settings().env}: set APP_MIGRATION_DATABASE_URL (the owner)", file=sys.stderr)
        return 2
    config = alembic_config(url)
    command.upgrade(config, "head")
    print(f"migrate: at head {ScriptDirectory.from_config(config).get_current_head()}")
    return 0


def revision() -> int:
    print(ScriptDirectory.from_config(alembic_config()).get_current_head())
    return 0


def downgrade(target: str | None) -> int:
    """Step down one migration at a time to `target`, printing each step; never past it, never to base (07/O5)."""
    url = owner_url()
    if url is None:
        print(f"downgrade: refusing in {get_settings().env}: set APP_MIGRATION_DATABASE_URL", file=sys.stderr)
        return 2
    if not target or target == "base" or target.startswith("-"):
        print("downgrade: name the older release's head with --to; never blind or relative", file=sys.stderr)
        return 2
    config = alembic_config(url)
    script = ScriptDirectory.from_config(config)
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            current = MigrationContext.configure(conn).get_current_revision()
    finally:
        engine.dispose()
    steps: list[tuple[str, str]] = []
    cursor = current
    while cursor is not None and cursor != target:
        try:
            found = script.get_revision(cursor)
        except RevisionError:
            found = None  # a revision this image doesn't know: only a newer image can step down from it
        down = found.down_revision if found else None
        if not isinstance(down, str):  # base, a merge, or an unknown revision
            print(f"downgrade: {target} is not below {current} in this image's history; refusing", file=sys.stderr)
            return 1
        steps.append((cursor, down))
        cursor = down
    if cursor != target:
        print(f"downgrade: the database is at {current}; {target} is not below it; refusing", file=sys.stderr)
        return 1
    for upper, lower in steps:
        command.downgrade(config, "-1")
        print(f"downgrade: {upper} -> {lower}")
    print(f"downgrade: at {target} ({len(steps)} step(s))")
    return 0


def config_check() -> int:
    settings = get_settings()
    found = deployed_config.problems(settings)
    for problem in found:
        print(f"config-check: {problem}")
    print(f"config-check: {settings.env}: {'refused' if found else 'safe to start'} ({len(found)} problem(s))")
    return 1 if found else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="skeleton_proof_e_next_ai.run",
        description=__doc__.splitlines()[0],
    )
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("--to", help="downgrade only: the revision to step down to")
    args = parser.parse_args(argv)
    if "APP_ENV" not in os.environ:
        print("run: APP_ENV is not set; the environment is always explicit (07/O3)", file=sys.stderr)
        return 2
    if args.command == "api":
        return serve("skeleton_proof_e_next_ai.api.app:create_app")
    if args.command == "worker":
        run_worker()
        return 0
    if args.command == "downgrade":
        return downgrade(args.to)
    return {"migrate": migrate, "revision": revision, "config-check": config_check}[args.command]()


if __name__ == "__main__":
    sys.exit(main())
