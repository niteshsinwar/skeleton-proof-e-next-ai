"""Rate limits, upload intake, webhook signatures and business configuration (01/R2, 05/SG6, 02/I4, 02/B5)."""

from __future__ import annotations

import base64
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from skeleton_proof_e_next_ai.integrations.webhooks.verify import InvalidWebhook, sign, verify
from skeleton_proof_e_next_ai.persistence import business_config
from skeleton_proof_e_next_ai.security.rate_limit import (
    LIMITS,
    Limit,
    MemoryRateLimiter,
    PostgresRateLimiter,
    gcra,
)
from skeleton_proof_e_next_ai.security.uploads import UploadRejected, validate

T0 = datetime(2026, 11, 4, tzinfo=UTC)
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def test_gcra_allows_the_burst_then_denies_with_retry_after() -> None:
    limit, tat, results = Limit(per_second=1, burst=3), None, []
    for _ in range(4):
        decision, new = gcra(tat, T0, limit)
        results.append(decision.allowed)
        tat = new or tat
    assert results == [True, True, True, False]
    denied, _ = gcra(tat, T0, limit)
    assert denied.retry_after_seconds >= 1
    later, _ = gcra(tat, T0 + timedelta(seconds=5), limit)
    assert later.allowed


def _allowed_in_a_burst(limit: Limit) -> int:
    tat, allowed = None, 0
    for _ in range(100):
        decision, new = gcra(tat, T0, limit)
        if not decision.allowed:
            break
        tat, allowed = new, allowed + 1
    return allowed


def test_agents_are_a_stricter_traffic_class_than_humans() -> None:
    """Agents get their own, smaller quota in every endpoint class, so a burst of agent calls is refused while a
    human doing the same still gets through: humans are protected first under load (01/R3, 01/R4)."""
    assert LIMITS, "no endpoint classes defined"
    for endpoint_class, by_kind in LIMITS.items():
        human, agent = by_kind["human"], by_kind["agent"]
        assert agent.per_second <= human.per_second and agent.burst <= human.burst, endpoint_class
        assert _allowed_in_a_burst(agent) < _allowed_in_a_burst(human), endpoint_class


@pytest.mark.anyio
async def test_memory_limiter_keys_are_independent() -> None:
    limiter, limit = MemoryRateLimiter(), Limit(per_second=1, burst=1)
    assert (await limiter.check("a", limit, T0)).allowed
    assert not (await limiter.check("a", limit, T0)).allowed
    assert (await limiter.check("b", limit, T0)).allowed


def test_upload_needs_an_allowlisted_type_whose_bytes_agree() -> None:
    assert validate("image/png", PNG) == ".png"
    assert validate("image/png; charset=binary", PNG) == ".png"
    with pytest.raises(UploadRejected):
        validate("image/png", b"%PDF-1.7 renamed")  # magic bytes disagree with the declared type
    with pytest.raises(UploadRejected):
        validate("application/zip", b"PK\x03\x04")  # not allowlisted (no archives: no bombs)
    with pytest.raises(UploadRejected):
        validate("", PNG)


SECRET = "whsec_" + base64.b64encode(b"test-secret-32-bytes-long-enough").decode()


def test_webhook_signature_valid_tampered_stale_and_rotated() -> None:
    body, now = b'{"event":"paid"}', 1_800_000_000
    headers = {
        "webhook-id": "msg_1",
        "webhook-timestamp": str(now),
        "webhook-signature": sign(SECRET, "msg_1", now, body),
    }
    assert verify([SECRET], headers, body, now) == "msg_1"
    with pytest.raises(InvalidWebhook):
        verify([SECRET], headers, body + b" ", now)  # body tampered
    with pytest.raises(InvalidWebhook):
        verify([SECRET], headers, body, now + 301)  # outside the 5-minute window
    old = "whsec_" + base64.b64encode(b"old-secret-also-32-bytes-long!!!").decode()
    rotated = {**headers, "webhook-signature": f"{sign(old, 'msg_1', now, body)} {headers['webhook-signature']}"}
    assert verify([SECRET], rotated, body, now) == "msg_1"  # several signatures during rotation


def test_business_config_is_strict_and_resolves_by_date(tmp_path: Path) -> None:
    good = tmp_path / "good"
    good.mkdir()
    (good / "business.toml").write_text(
        "[[work_items]]\nversion = 1\neffective_from = 2026-01-01\nmax_title_length = 200\n"
        "[[work_items]]\nversion = 2\neffective_from = 2026-06-01\nmax_title_length = 120\n"
    )
    cfg = business_config.load(good)
    assert cfg.work_item_policy(date(2026, 3, 1)).max_title_length == 200
    assert cfg.work_item_policy(date(2026, 7, 1)).max_title_length == 120
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "business.toml").write_text(
        "[[work_items]]\nversion = 1\neffective_from = 2026-01-01\nmax_title_length = 200\nmax_titel = 3\n"
    )
    with pytest.raises(ValidationError):
        business_config.load(bad)  # an unknown key raises; it never falls back to a default (02/B5)


def test_the_shipped_business_config_loads() -> None:
    business_config.load(Path(__file__).resolve().parents[2] / "config")


@pytest.mark.parametrize("role", ['app"; DROP ROLE app_user; --', "App_User", "app user", "r" * 64, "rôle"])
def test_the_postgres_limiter_refuses_a_role_that_is_not_a_plain_identifier(role: str) -> None:
    """The role is interpolated into SET LOCAL ROLE, so the limiter checks it itself (found by Semgrep, B5-3)."""
    with pytest.raises(ValueError, match="plain lowercase identifiers"):
        PostgresRateLimiter(engine=None, role=role)  # type: ignore[arg-type]  (refused before the engine is used)


def test_the_postgres_limiter_accepts_a_plain_role_or_none() -> None:
    assert PostgresRateLimiter(engine=None, role="app_user").role == "app_user"  # type: ignore[arg-type]
    assert PostgresRateLimiter(engine=None, role=None).role is None  # type: ignore[arg-type]
