"""One registry for job handlers, keyed uniquely (02/B4). A handler module that registers nothing fails a test."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from ..persistence.db import Database

Handler = Callable[[dict[str, Any], Database], Awaitable[bool]]  # returns True when a human must review


class Registry:
    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    def handler(self, kind: str) -> Callable[[Handler], Handler]:
        def register(fn: Handler) -> Handler:
            if kind in self._handlers:
                raise ValueError(f"job kind '{kind}' is already registered")
            self._handlers[kind] = fn
            return fn

        return register

    def get(self, kind: str) -> Handler | None:
        return self._handlers.get(kind)

    @property
    def kinds(self) -> frozenset[str]:
        return frozenset(self._handlers)


REGISTRY = Registry()
