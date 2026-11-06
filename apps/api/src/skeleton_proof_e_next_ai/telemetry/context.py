"""Correlation, causation and actor travel in contextvars (02/B8, 07/O7)."""

from __future__ import annotations

import uuid
from contextvars import ContextVar

correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")
causation_id: ContextVar[str] = ContextVar("causation_id", default="-")
actor: ContextVar[str] = ContextVar("actor", default="-")
tenant: ContextVar[str] = ContextVar("tenant", default="-")


def new_correlation_id() -> str:
    return str(uuid.uuid7())
