"""The model gateway: the one module that calls models (01/C5, 02/B8, 13/V7).

A route resolves to a model and its provider (plans/b4 D13). A provider exists only when its credential is configured;
a route whose provider has none runs with AI off, which is a stated mode, never an error (01/R5, 01/C4). Retries are
spent from one budget per call, with jittered backoff that honours `Retry-After`, and only for transient failures
(01/R6, 02/I2). Cost is computed from the catalogue's dated price, never estimated (04/M3).
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ..domain.ai import ExecutionMode, Usage
from .catalogue import Catalogue, cost_usd
from .providers import LLMRequest, LLMResponse, Provider, ProviderError
from .providers.anthropic import AnthropicProvider

BACKOFF_BASE_SECONDS = 0.5
BACKOFF_CAP_SECONDS = 8.0


def backoff_seconds(attempt: int, retry_after: float | None, jitter: Callable[[], float]) -> float:
    """Full-jitter exponential backoff, capped; the provider's `Retry-After` wins when it gives one (01/R6)."""
    if retry_after is not None:
        return min(retry_after, BACKOFF_CAP_SECONDS)
    return float(min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS * 2 ** (attempt - 1)) * jitter())


@dataclass(frozen=True, slots=True)
class Outcome:
    """What one gateway call produced. Exactly one of `response` and `failure` is set."""

    route: str
    mode: ExecutionMode
    provider: str | None
    model_id: str | None
    response: LLMResponse | None
    failure: str | None  # a stable reason code: "ai_off", "provider_unavailable", "rate_limited", ...
    attempts: int
    usage: Usage


class Gateway:
    def __init__(
        self,
        catalogue: Catalogue,
        providers: Mapping[str, Provider],
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self.catalogue = catalogue
        self._providers = dict(providers)
        self._sleep, self._jitter = sleep, jitter

    @classmethod
    def from_environment(cls, catalogue: Catalogue, env: Mapping[str, str]) -> Gateway:
        """Build the providers whose credentials are set. The credential is read here and nowhere else."""
        providers: dict[str, Provider] = {}
        for name, spec in catalogue.providers.items():
            if spec.adapter == "anthropic":
                key = env.get(spec.credential_env or "", "")
                if key:
                    providers[name] = AnthropicProvider(name, key, refusal_fallback=spec.refusal_fallback == "default")
            # The fake is never built from the environment: tests and the eval self-test pass it in (06/T4).
        return cls(catalogue, providers)

    def available(self, route: str) -> bool:
        return self.catalogue.model_for(route).provider in self._providers

    def mode_for(self, route: str) -> ExecutionMode:
        provider = self._providers.get(self.catalogue.model_for(route).provider)
        return provider.mode if provider is not None else ExecutionMode.AI_OFF

    async def call(
        self,
        route: str,
        *,
        system: str,
        user: str,
        output_schema: Mapping[str, Any],
        effort: str | None = None,
        max_output_tokens: int | None = None,
    ) -> Outcome:
        spec = self.catalogue.route(route)
        model = self.catalogue.models[spec.model]
        provider = self._providers.get(model.provider)
        if provider is None:
            return Outcome(route, ExecutionMode.AI_OFF, None, None, None, "ai_off", 0, Usage.none_spent())
        request = LLMRequest(
            model_id=model.id,
            effort=effort or spec.effort,
            system=system,
            user=user,
            output_schema=output_schema,
            max_output_tokens=max_output_tokens or spec.max_output_tokens,
            timeout_seconds=spec.timeout_seconds,
        )
        last: ProviderError | None = None
        for attempt in range(1, spec.max_attempts + 1):
            try:
                response = await provider.complete(request)
            except ProviderError as exc:
                last = exc
                if not exc.retryable or attempt == spec.max_attempts:
                    break
                await self._sleep(self._backoff(attempt, exc.retry_after))
                continue
            return Outcome(
                route,
                provider.mode,
                provider.name,
                model.id,
                response,
                None,
                attempt,
                self._usage(route, response, provider),
            )
        if last is None:  # unreachable: the loop only ends without a response after an error
            raise RuntimeError("gateway retry loop ended without a response or an error")
        reason = {"unavailable": "provider_unavailable", "rate_limited": "rate_limited"}.get(
            last.kind, f"provider_{last.kind}"
        )
        return Outcome(
            route,
            provider.mode,
            provider.name,
            model.id,
            None,
            reason,
            attempt,
            Usage.none_spent() if provider.mode is not ExecutionMode.LIVE else Usage(),
        )

    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        return backoff_seconds(attempt, retry_after, self._jitter)

    def _usage(self, route: str, response: LLMResponse, provider: Provider) -> Usage:
        if provider.mode is not ExecutionMode.LIVE:
            return Usage.none_spent()
        tokens = (response.input_tokens, response.output_tokens)
        if any(t is None for t in tokens):
            return Usage(input_tokens=response.input_tokens, output_tokens=response.output_tokens)  # unknown stays None
        price = self.catalogue.model_for(route).price
        snapshot = price.snapshot
        if response.served_model != self.catalogue.model_for(route).id:
            # The provider's refusal fallback answered on another model: use its rate if we know it, else say so.
            served = next((m for m in self.catalogue.models.values() if m.id == response.served_model), None)
            if served is not None:
                price, snapshot = served.price, served.price.snapshot
            else:
                snapshot = f"{price.snapshot} (requested model's rate; served by {response.served_model})"
        return Usage(
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cache_read_tokens=response.cache_read_tokens,
            cache_write_tokens=response.cache_write_tokens,
            cost_usd=cost_usd(
                price,
                input_tokens=response.input_tokens or 0,
                output_tokens=response.output_tokens or 0,
                cache_read=response.cache_read_tokens or 0,
                cache_write=response.cache_write_tokens or 0,
            ),
            price_snapshot=snapshot,
        )
