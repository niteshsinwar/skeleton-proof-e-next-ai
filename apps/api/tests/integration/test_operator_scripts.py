"""Operator scripts that write refuse production unless a named person authorised the write, recorded in the audit
(02/I7, 05/SG10). Both ways, on a real database: refused and nothing written; authorised, written and attributed."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from skeleton_proof_e_next_ai.config.project import DEFAULT_TENANT, MULTI_TENANT

pytestmark = pytest.mark.integration
API = Path(__file__).resolve().parents[2]
SCRIPTS = API.parents[1] / "scripts"
TENANT = "00000000-0000-0000-0000-00000000000a" if MULTI_TENANT else str(DEFAULT_TENANT)


def operator(script: str, database: str, *args: str, env: str = "production") -> subprocess.CompletedProcess[str]:
    """As an operator runs it (`make grant`): the package on the path, APP_ENV from the environment."""
    environ = {**os.environ, "APP_ENV": env, "PYTHONPATH": str(API / "src")}
    argv = [sys.executable, str(SCRIPTS / script), "--database", database, *args]
    return subprocess.run(argv, capture_output=True, text=True, env=environ, check=False, timeout=60)  # noqa: S603


def audit_reasons(database: str, entity_id: str) -> list[str]:
    engine = create_engine(database)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT reason FROM audit.events WHERE entity_id = :e"), {"e": entity_id}).all()
    engine.dispose()
    return [r.reason for r in rows]


def test_grant_role_in_production_needs_a_named_authoriser(migrated: str) -> None:
    grant = ["--sub", "operator-guard", "--role", "approver", "--reason", "covering the queue"]
    grant += ["--tenant", TENANT]
    refused = operator("grant_role.py", migrated, *grant)
    assert refused.returncode != 0 and "02/I7" in refused.stderr, refused.stderr
    assert audit_reasons(migrated, "operator-guard:approver") == [], "a refused write wrote nothing"

    done = operator("grant_role.py", migrated, *grant, "--authorised-by", "Dana Reyes (ops lead)")
    assert done.returncode == 0, done.stderr
    assert audit_reasons(migrated, "operator-guard:approver") == [
        "covering the queue [authorised by Dana Reyes (ops lead)]"
    ], "the audit row names the person who authorised it"


def test_outside_production_the_reason_alone_is_enough(migrated: str) -> None:
    grant = ["--sub", "operator-local", "--role", "member", "--reason", "local demo"]
    grant += ["--tenant", TENANT]
    done = operator("grant_role.py", migrated, *grant, env="local")
    assert done.returncode == 0, done.stderr
    assert audit_reasons(migrated, "operator-local:member") == ["local demo"]
