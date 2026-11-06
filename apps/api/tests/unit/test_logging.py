"""Logs carry the request context but never secrets (05/SG8, 07/O7): a replayed leak is caught here."""

from __future__ import annotations

import json
import logging

from skeleton_proof_e_next_ai.telemetry.logging import REDACTED_KEYS, JsonFormatter


def _line(**fields: object) -> dict[str, object]:
    record = logging.LogRecord("app", logging.INFO, __file__, 1, "signed in", None, None)
    record.fields = fields
    parsed: dict[str, object] = json.loads(JsonFormatter().format(record))
    return parsed


def test_secret_fields_are_redacted_whatever_their_case() -> None:
    line = _line(Authorization="Bearer eyJsecret", password="hunter2", Cookie="session=abc", api_key="k-1")
    assert {line["Authorization"], line["password"], line["Cookie"], line["api_key"]} == {"[redacted]"}
    assert "eyJsecret" not in json.dumps(line) and "hunter2" not in json.dumps(line)


def test_ordinary_fields_and_the_context_are_kept() -> None:
    line = _line(work_item="0b4f8c3e", outcome="approved")
    kept = (line["work_item"], line["outcome"], line["msg"], line["level"])
    assert kept == ("0b4f8c3e", "approved", "signed in", "INFO")
    assert {"correlation_id", "actor", "tenant"} <= line.keys()
    assert {"authorization", "password", "token", "secret", "cookie"} <= REDACTED_KEYS
