#!/usr/bin/env python3
"""Expiry is monitored, so nothing lapses unnoticed (07/O18, O23): `make expiry-check`, run nightly and before go-live.

Fails when something lapses within its window and warns earlier:
- a model or embedding model a route uses retires within 30 days (warns from 90): a rollback point on a retired model
  is not a rollback point (07/O23), and the app refuses to start on one already retired (intelligence/catalogue.py);
- a TLS certificate of a host listed in EXPIRY_HOSTS (`host` or `host:port`, comma-separated) expires within 21 days
  (warns from 45): one project's expired certificate failed every production callout for 18 days.
Today is injectable (`--today`), so tests never depend on the date (06/T10).

  cd apps/api && PYTHONPATH=src uv run python ../../scripts/expiry_check.py [--today 2026-11-06] [--hosts a.example.com]
"""

from __future__ import annotations

import argparse
import os
import socket
import ssl
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from skeleton_proof_e_next_ai.intelligence import catalogue as ai_catalogue

MODEL_FAIL, MODEL_WARN = 30, 90
CERT_FAIL, CERT_WARN = 21, 45


@dataclass(frozen=True)
class Finding:
    level: str  # "fail" or "warn"
    what: str
    days: int


def judge(what: str, days: int, fail: int, warn: int) -> Finding | None:
    if days <= fail:
        return Finding("fail", what, days)
    if days <= warn:
        return Finding("warn", what, days)
    return None


def model_findings(path: Path, today: date) -> tuple[list[Finding], int]:
    """Every model and embedding model the catalogue's routes use, judged by its retirement date."""
    catalogue = ai_catalogue.load(path, today=today, production=False)
    used = {route.model for route in catalogue.routes.values()}
    dated = {f"model {m}": catalogue.models[m].retires_on for m in sorted(used)}
    dated |= {f"embedding {n}": e.retires_on for n, e in sorted(catalogue.embeddings.items())}
    found = [
        f
        for what, retires in dated.items()
        if retires is not None and (f := judge(what, (retires - today).days, MODEL_FAIL, MODEL_WARN))
    ]
    return found, len(dated)


def certificate_days(host: str, today: date, timeout: float = 5.0) -> int:
    name, _, port = host.partition(":")
    context = ssl.create_default_context()
    with socket.create_connection((name, int(port or 443)), timeout=timeout) as raw:
        with context.wrap_socket(raw, server_hostname=name) as tls:
            cert = tls.getpeercert()
    not_after = datetime.fromtimestamp(ssl.cert_time_to_seconds(str(cert["notAfter"])), tz=UTC).date()
    return (not_after - today).days


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--today", type=date.fromisoformat, default=datetime.now(UTC).date())
    parser.add_argument("--hosts", default=os.environ.get("EXPIRY_HOSTS", ""))
    args = parser.parse_args(argv)
    findings: list[Finding] = []
    examined = 0
    models, count = model_findings(Path(__file__).resolve().parents[1] / "ai" / "models.yaml", args.today)
    findings += models
    examined += count
    for host in [h.strip() for h in args.hosts.split(",") if h.strip()]:
        examined += 1
        try:
            days = certificate_days(host, args.today)
        except (OSError, ssl.SSLError) as exc:  # an unreachable or invalid certificate is a failure, never a pass
            findings.append(Finding("fail", f"certificate of {host} ({type(exc).__name__})", 0))
            continue
        if (found := judge(f"certificate of {host}", days, CERT_FAIL, CERT_WARN)) is not None:
            findings.append(found)
    for f in findings:
        print(f"expiry-check: {f.level.upper()} {f.what}: {f.days} day(s) left")
    failed = [f for f in findings if f.level == "fail"]
    print(f"expiry-check: examined {examined} dated item(s); {len(failed)} failing, {len(findings) - len(failed)} warning")
    if not args.hosts.strip():
        # Nothing silently passes (10/H18): with no hosts listed, no certificate is being watched, and it says so.
        print("expiry-check: OPEN no certificate is watched: list the deployed hosts in EXPIRY_HOSTS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
