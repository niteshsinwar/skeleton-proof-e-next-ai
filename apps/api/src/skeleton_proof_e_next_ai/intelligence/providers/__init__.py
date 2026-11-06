"""The provider port: one request and one response shape for every model provider (02/B3, 13/V7).

An adapter translates exactly this and nothing more. It makes one call; retries, budgets, records and decisions live in
the gateway and the step runner, so a new provider can't bring its own behaviour with it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from ...domain.ai import ExecutionMode

Stop = Literal["end", "truncated", "refused", "other"]
ErrorKind = Literal["unavailable", "rate_limited", "auth", "bad_request", "provider_error"]


@dataclass(frozen=True, slots=True)
class LLMRequest:
    model_id: str
    effort: str
    system: str  # the agent's stable policy text: cached, and never holds user or record text (04/X2, 05/SG5)
    user: str  # the rendered task, with every context item inside its own data block
    output_schema: Mapping[str, Any]  # JSON Schema the provider constrains its output to (04/Q4)
    max_output_tokens: int
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str | None
    stop: Stop
    served_model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    refusal_category: str | None = None


class ProviderError(Exception):
    """One failed call. `retryable` decides whether the gateway may spend another attempt from its budget.

    A per-minute rate limit is retryable; an exhausted spend or credit balance is not (Aegis H: "quota exhaustion
    classified as transient" was a failure).
    """

    def __init__(self, kind: ErrorKind, detail: str, *, retryable: bool, retry_after: float | None = None) -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind, self.retryable, self.retry_after = kind, retryable, retry_after


class Provider(Protocol):
    name: str

    @property
    def mode(self) -> ExecutionMode: ...

    async def complete(self, request: LLMRequest) -> LLMResponse: ...
