"""The labelled fake provider (06/T4). It proves plumbing (retries, timeouts, fail-closed paths, records, harness
verdicts); it never proves behaviour, and everything it produces is recorded as `fixture`, so it can't be counted as an
eval or shown as a live answer.

Script it with replies, one per call:  FakeProvider("fake", [Reply.json({...}), Reply.down(), Reply.truncated()])
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ...domain.ai import ExecutionMode
from . import ErrorKind, LLMRequest, LLMResponse, ProviderError, Stop


@dataclass(frozen=True, slots=True)
class Reply:
    text: str | None = None
    stop: Stop = "end"
    error: ErrorKind | None = None
    retryable: bool = True
    retry_after: float | None = None
    served_model: str | None = None

    @staticmethod
    def json(value: Mapping[str, Any], served_model: str | None = None) -> Reply:
        return Reply(text=json.dumps(value), served_model=served_model)

    @staticmethod
    def raw(text: str) -> Reply:
        return Reply(text=text)

    @staticmethod
    def truncated(text: str = '{"points": [') -> Reply:
        return Reply(text=text, stop="truncated")

    @staticmethod
    def refused() -> Reply:
        return Reply(text=None, stop="refused")

    @staticmethod
    def down() -> Reply:
        return Reply(error="unavailable", retryable=True)

    @staticmethod
    def failing(kind: ErrorKind, *, retryable: bool, retry_after: float | None = None) -> Reply:
        return Reply(error=kind, retryable=retryable, retry_after=retry_after)


@dataclass
class FakeProvider:
    name: str
    replies: list[Reply] = field(default_factory=list)
    calls: list[LLMRequest] = field(default_factory=list)

    @property
    def mode(self) -> ExecutionMode:
        """Always a fixture: a fake can't be labelled live, whatever builds it (06/T4)."""
        return ExecutionMode.FIXTURE

    @classmethod
    def scripted(cls, name: str, replies: Iterable[Reply]) -> FakeProvider:
        return cls(name=name, replies=list(replies))

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        if not self.replies:
            raise ProviderError("provider_error", "the fake has no scripted reply left", retryable=False)
        reply = self.replies.pop(0)
        if reply.error is not None:
            raise ProviderError(
                reply.error, "scripted failure", retryable=reply.retryable, retry_after=reply.retry_after
            )
        return LLMResponse(
            text=reply.text,
            stop=reply.stop,
            served_model=reply.served_model or request.model_id,
            refusal_category="fixture" if reply.stop == "refused" else None,
        )
