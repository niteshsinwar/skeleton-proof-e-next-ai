"""Shared helpers for the AI unit tests: a catalogue on two fake providers, agent files written to a temporary folder,
and a principal. Everything is offline; nothing here can reach a real model (06/T4)."""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml

from skeleton_proof_e_next_ai.domain.ai import ContextItem, DataClass, Trust
from skeleton_proof_e_next_ai.domain.principals import Principal, PrincipalKind
from skeleton_proof_e_next_ai.intelligence import catalogue as cat
from skeleton_proof_e_next_ai.intelligence.agents import Agent, load_agents

TENANT = UUID(int=10)
OTHER_TENANT = UUID(int=11)
PRICE = {
    "snapshot": "test-2026-11-01",
    "input_per_mtok": "2.00",
    "output_per_mtok": "10.00",
    "cache_read_per_mtok": "0.20",
    "cache_write_per_mtok": "2.50",
}
CATALOGUE: dict[str, Any] = {
    "version": 1,
    "providers": {"alpha": {"adapter": "fake"}, "beta": {"adapter": "fake"}},
    "models": {
        "a-large": {"provider": "alpha", "id": "a-large-1", "family": "a", "price": PRICE},
        "b-small": {"provider": "beta", "id": "b-small-1", "family": "b", "price": PRICE},
    },
    "routes": {"default": {"model": "a-large"}, "fast": {"model": "b-small", "effort": "low"}},
    "limits": {"tenant_daily_usd": "1.00"},
}
AGENT: dict[str, Any] = {
    "agent": "summary",
    "version": 1,
    "job": "Summarise the record for the person who decides on it.",
    "decided_after_by": "human",
    "must_never": ["decide on the record", "invent a fact"],
    "pattern": "single_call",
    "route": "default",
    "grounding": {
        "max_context_tokens": 2000,
        "sources": {"record.title": {"max_chars": 200}, "record.details": {"max_chars": 4000}},
    },
    "prompt": {"system": "You write short, careful summaries.", "task": "Summarise for a $audience.\n\n$context"},
    "variables": {"audience": {"max_chars": 40}},
    "output": "Summary",
    "evals": {"dataset": "summary", "version": 1},
}


def catalogue(**routes: Any) -> cat.Catalogue:
    data = copy.deepcopy(CATALOGUE)
    data["routes"].update(routes)
    return cat.Catalogue.model_validate(data)


def write_agent(root: Path, **changes: Any) -> Path:
    data = copy.deepcopy(AGENT) | changes
    folder = root / data["agent"]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"v{data['version']}.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


def agents(root: Path, **changes: Any) -> dict[str, Agent]:
    write_agent(root, **changes)
    return load_agents(root, catalogue())


def principal(tenant: UUID = TENANT) -> Principal:
    return Principal(subject="alice", kind=PrincipalKind.HUMAN, tenant_id=tenant, roles=frozenset({"member"}))


def item(text: str, source: str = "record.details", **kw: Any) -> ContextItem:
    return ContextItem(
        source=source,
        ref=kw.pop("ref", "record:1"),
        text=text,
        trust=kw.pop("trust", Trust.RECORD),
        tenant_id=kw.pop("tenant_id", TENANT),
        data_class=kw.pop("data_class", DataClass.INTERNAL),
        **kw,
    )


class Clock:
    """An injected clock that moves a second per reading (06/T10: no real time in tests)."""

    def __init__(self) -> None:
        self.now = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now
