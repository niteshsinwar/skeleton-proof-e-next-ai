#!/usr/bin/env python3
"""Grant or revoke a role directly in the database: the bootstrap for the first admin (02/Z5).

  make grant ARGS="--sub alice --role admin --reason 'first admin'"
  make grant ARGS="--sub alice --role admin --revoke --reason 'left the team'"

After the first admin exists, roles change through the audited admin API (POST /admin/roles/{subject}/grant),
which refuses self-grants. This script connects as APP_DATABASE_URL (the owner, from .env), so it is an operator
action, never an app path; every change it makes is written to the audit trail too (05/SG10).
In production (APP_ENV=production) it refuses unless --authorised-by names the person who authorised the write,
and the audit row records them (02/I7).
"""

from __future__ import annotations

import argparse
import getpass
import os
import uuid
from datetime import UTC, datetime

from sqlalchemy import create_engine, text

from skeleton_proof_e_next_ai.config.project import DEFAULT_TENANT, MULTI_TENANT
from skeleton_proof_e_next_ai.domain.principals import ROLE_CAPABILITIES
from skeleton_proof_e_next_ai.persistence import audit_chain

GRANT = (
    "INSERT INTO app.role_grants (tenant_id, subject, role, granted_by, granted_at) VALUES (:t, :s, :r, :by, :at) "
    "ON CONFLICT (tenant_id, subject, role) DO UPDATE "
    "SET granted_by = :by, granted_at = :at, revoked_by = NULL, revoked_at = NULL"
)
REVOKE = (
    "UPDATE app.role_grants SET revoked_by = :by, revoked_at = :at "
    "WHERE tenant_id = :t AND subject = :s AND role = :r AND revoked_at IS NULL"
)
AUDIT = (
    "INSERT INTO audit.events (id, at, tenant_id, action, entity, entity_id, actor, principal_kind, reason, "
    "correlation_id, sequence, prev_hash, hash) VALUES (:id, :at, :t, :action, 'role_grant', :eid, :by, 'human', "
    ":why, 'operator', :seq, :prev, :hash)"
)


def production_guard(authorised_by: str | None, reason: str) -> str:
    """02/I7: in production a write needs a named person who authorised it, and the audit row says who."""
    if os.environ.get("APP_ENV") == "production":
        if not (authorised_by or "").strip() or not reason.strip():
            raise SystemExit(
                "refusing to write to production without --authorised-by <a named person> and a --reason (02/I7)"
            )
        return f"{reason} [authorised by {(authorised_by or '').strip()}]"
    return reason


def main() -> None:
    p = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    p.add_argument("--sub", required=True, action="append", help="repeat for several people")
    p.add_argument("--role", required=True, choices=sorted(ROLE_CAPABILITIES))
    p.add_argument("--reason", required=True)
    p.add_argument("--tenant", help="multi-tenant projects: the tenant id (single-tenant uses the default tenant)")
    p.add_argument("--revoke", action="store_true")
    p.add_argument("--database", default=os.environ.get("APP_DATABASE_URL"))
    p.add_argument("--authorised-by", help="production only: the named person who authorised this write (02/I7)")
    a = p.parse_args()
    why = production_guard(a.authorised_by, a.reason)
    if not a.database:
        raise SystemExit("set APP_DATABASE_URL or pass --database")
    if MULTI_TENANT and not a.tenant:
        raise SystemExit("multi-tenant project: pass --tenant")
    tenant = uuid.UUID(a.tenant) if MULTI_TENANT else DEFAULT_TENANT
    actor, now = f"operator:{getpass.getuser()}", datetime.now(UTC)
    engine = create_engine(a.database)
    with engine.begin() as conn:
        for sub in a.sub:
            values = {"t": tenant, "s": sub, "r": a.role, "by": actor, "at": now}
            conn.execute(text(REVOKE if a.revoke else GRANT), values)
            action = "role.revoked" if a.revoke else "role.granted"
            audit = {"id": uuid.uuid4(), "at": now, "t": tenant, "action": action, "eid": f"{sub}:{a.role}"}
            # tier E: the row joins the tenant's hash chain under the head's lock, like every audit write (02/D6)
            event = {**audit, "tenant_id": tenant, "entity": "role_grant", "entity_id": audit["eid"], "actor": actor,
                     "principal_kind": "human", "reason": why, "correlation_id": "operator"}
            conn.execute(text(audit_chain.HEAD_INIT), {"t": tenant})
            head = conn.execute(text(audit_chain.HEAD_LOCK), {"t": tenant}).one()
            seq = int(head.sequence) + 1
            digest = audit_chain.link(str(tenant), seq, head.hash, event)
            conn.execute(text(audit_chain.HEAD_MOVE), {"s": seq, "h": digest, "t": tenant})
            conn.execute(text(AUDIT), {**audit, "by": actor, "why": why, "seq": seq, "prev": head.hash, "hash": digest})
            print(f"{action} {a.role} for {sub}")
    engine.dispose()


if __name__ == "__main__":
    main()
