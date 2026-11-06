"""The model catalogue and the gateway (01/C5, 01/R6, 04/M1–M3, 06/T4; plans/b4 D13).

Every test runs offline with fake providers; nothing here proves model behaviour, only the plumbing around it.
"""

from __future__ import annotations

import copy
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import anthropic
import httpx2
import pytest
import yaml

from skeleton_proof_e_next_ai.domain.ai import ExecutionMode
from skeleton_proof_e_next_ai.intelligence import catalogue as cat
from skeleton_proof_e_next_ai.intelligence.gateway import Gateway
from skeleton_proof_e_next_ai.intelligence.providers import LLMRequest, LLMResponse, ProviderError
from skeleton_proof_e_next_ai.intelligence.providers.anthropic import AnthropicProvider, _response
from skeleton_proof_e_next_ai.intelligence.providers.fake import FakeProvider, Reply

pytestmark = pytest.mark.anyio

MODELS_YAML = Path(__file__).resolve().parents[4] / "ai" / "models.yaml"
TODAY = date(2026, 11, 5)
SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}

PRICE = {
    "snapshot": "test-2026-11-01",
    "input_per_mtok": "2.00",
    "output_per_mtok": "10.00",
    "cache_read_per_mtok": "0.20",
    "cache_write_per_mtok": "2.50",
}
TWO_PROVIDERS: dict[str, Any] = {
    "version": 1,
    "providers": {"alpha": {"adapter": "fake"}, "beta": {"adapter": "fake"}},
    "models": {
        "a-large": {"provider": "alpha", "id": "a-large-1", "family": "a", "price": PRICE},
        "b-small": {"provider": "beta", "id": "b-small-1", "family": "b", "price": PRICE},
    },
    "routes": {"default": {"model": "a-large"}, "fast": {"model": "b-small", "effort": "low"}},
    "limits": {"tenant_daily_usd": "1.00"},
}


def catalogue(raw: dict[str, Any] | None = None, **changes: Any) -> cat.Catalogue:
    data = copy.deepcopy(raw or TWO_PROVIDERS)
    for path, value in changes.items():
        node = data
        *parents, leaf = path.split("__")
        for p in parents:
            node = node[p]
        node[leaf] = value
    return cat.Catalogue.model_validate(data)


def write(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


async def no_sleep(_: float) -> None:
    return None


# --- the catalogue -----------------------------------------------------------------------------------------------


def test_the_shipped_catalogue_loads_and_has_a_default_route() -> None:
    loaded = cat.load(MODELS_YAML, today=TODAY, production=True)
    assert "default" in loaded.routes
    assert loaded.provider_for("default").adapter == "anthropic"
    assert all(m.price.snapshot for m in loaded.models.values())


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"routes__default__model": "nope"}, "unknown model"),
        ({"models__a-large__provider": "gamma"}, "unknown provider"),
        ({"routes__default__colour": "blue"}, "Extra inputs"),
        ({"routes": {"fast": {"model": "b-small"}}}, "default"),
        ({"routes__judge": {"model": "a-large"}}, "different model family"),
    ],
)
def test_a_wrong_catalogue_is_refused_at_start(tmp_path: Path, change: dict[str, Any], message: str) -> None:
    data = copy.deepcopy(TWO_PROVIDERS)
    for path, value in change.items():
        node = data
        *parents, leaf = path.split("__")
        for p in parents:
            node = node[p]
        node[leaf] = value
    with pytest.raises(cat.CatalogueError, match=message):
        cat.load(write(tmp_path, data), today=TODAY, production=False)


def test_a_judge_on_another_family_is_accepted() -> None:
    raw = copy.deepcopy(TWO_PROVIDERS)
    raw["routes"] = {"default": {"model": "a-large"}, "judge": {"model": "b-small"}}
    assert catalogue(raw).route("judge").model == "b-small"


def test_a_retired_model_is_refused(tmp_path: Path) -> None:
    data = copy.deepcopy(TWO_PROVIDERS)
    data["models"]["a-large"]["retires_on"] = "2026-11-01"
    with pytest.raises(cat.CatalogueError, match="retired"):
        cat.load(write(tmp_path, data), today=TODAY, production=False)


def test_the_fake_provider_is_refused_in_production(tmp_path: Path) -> None:
    path = write(tmp_path, TWO_PROVIDERS)
    assert cat.load(path, today=TODAY, production=False)
    with pytest.raises(cat.CatalogueError, match="fake"):
        cat.load(path, today=TODAY, production=True)


def test_an_unknown_route_names_the_known_ones() -> None:
    with pytest.raises(cat.CatalogueError, match="default, fast"):
        catalogue().route("deep")


def test_cost_is_usage_times_the_pinned_rate() -> None:
    price = catalogue().models["a-large"].price
    got = cat.cost_usd(price, input_tokens=1_000_000, output_tokens=500_000, cache_read=100_000, cache_write=10_000)
    assert got == Decimal("2.00") + Decimal("5.00") + Decimal("0.02") + Decimal("0.025")


# --- routing and switching -----------------------------------------------------------------------------------------


async def test_each_route_reaches_its_own_provider_and_model() -> None:
    alpha = FakeProvider.scripted("alpha", [Reply.json({})])
    beta = FakeProvider.scripted("beta", [Reply.json({})])
    gw = Gateway(catalogue(), {"alpha": alpha, "beta": beta}, sleep=no_sleep)
    await gw.call("default", system="s", user="u", output_schema=SCHEMA)
    await gw.call("fast", system="s", user="u", output_schema=SCHEMA)
    assert [c.model_id for c in alpha.calls] == ["a-large-1"]
    assert [(c.model_id, c.effort) for c in beta.calls] == [("b-small-1", "low")]


async def test_switching_a_route_to_another_provider_is_one_line() -> None:
    alpha = FakeProvider.scripted("alpha", [])
    beta = FakeProvider.scripted("beta", [Reply.json({})])
    gw = Gateway(catalogue(routes__default__model="b-small"), {"alpha": alpha, "beta": beta}, sleep=no_sleep)
    outcome = await gw.call("default", system="s", user="u", output_schema=SCHEMA)
    assert (outcome.provider, outcome.model_id, alpha.calls) == ("beta", "b-small-1", [])


async def test_a_route_without_a_configured_provider_runs_with_ai_off() -> None:
    gw = Gateway(catalogue(), {"beta": FakeProvider.scripted("beta", [])}, sleep=no_sleep)
    outcome = await gw.call("default", system="s", user="u", output_schema=SCHEMA)
    assert (outcome.mode, outcome.failure, outcome.attempts) == (ExecutionMode.AI_OFF, "ai_off", 0)
    assert outcome.usage.cost_usd == 0 and outcome.usage.input_tokens is None
    assert not gw.available("default") and gw.available("fast")


def test_without_a_credential_nothing_is_built_and_with_one_the_adapter_is() -> None:
    shipped = cat.load(MODELS_YAML, today=TODAY, production=False)
    assert not Gateway.from_environment(shipped, {}).available("default")
    built = Gateway.from_environment(shipped, {"ANTHROPIC_API_KEY": "sk-test-not-a-real-key"})
    assert built.available("default")


# --- the retry budget ---------------------------------------------------------------------------------------------


async def test_transient_failures_are_retried_within_the_budget_with_jitter() -> None:
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    alpha = FakeProvider.scripted("alpha", [Reply.down(), Reply.down(), Reply.json({"ok": True})])
    gw = Gateway(catalogue(), {"alpha": alpha}, sleep=sleep, jitter=lambda: 0.5)
    outcome = await gw.call("default", system="s", user="u", output_schema=SCHEMA)
    assert outcome.response is not None and outcome.attempts == 3
    assert waits == [0.25, 0.5]  # base 0.5 s doubling, times the jitter


async def test_retries_stop_at_the_budget_and_the_failure_is_named() -> None:
    alpha = FakeProvider.scripted("alpha", [Reply.down()] * 5)
    gw = Gateway(catalogue(routes__default__max_attempts=2), {"alpha": alpha}, sleep=no_sleep)
    outcome = await gw.call("default", system="s", user="u", output_schema=SCHEMA)
    assert (outcome.response, outcome.failure, outcome.attempts, len(alpha.calls)) == (
        None,
        "provider_unavailable",
        2,
        2,
    )


async def test_a_non_transient_failure_is_never_retried() -> None:
    alpha = FakeProvider.scripted("alpha", [Reply.failing("bad_request", retryable=False), Reply.json({})])
    gw = Gateway(catalogue(), {"alpha": alpha}, sleep=no_sleep)
    outcome = await gw.call("default", system="s", user="u", output_schema=SCHEMA)
    assert (outcome.failure, outcome.attempts) == ("provider_bad_request", 1)


async def test_retry_after_from_the_provider_is_honoured() -> None:
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    alpha = FakeProvider.scripted(
        "alpha", [Reply.failing("rate_limited", retryable=True, retry_after=3.0), Reply.json({})]
    )
    await Gateway(catalogue(), {"alpha": alpha}, sleep=sleep).call(
        "default", system="s", user="u", output_schema=SCHEMA
    )
    assert waits == [3.0]


# --- cost and modes -------------------------------------------------------------------------------------------------


class LiveStub:
    """A test double that reports itself live, to exercise the cost path. Never used outside this file."""

    name = "alpha"
    mode = ExecutionMode.LIVE

    def __init__(self, served: str = "a-large-1") -> None:
        self.served = served

    async def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse("{}", "end", self.served, 1_000, 2_000, 300, 0)


async def test_a_live_call_is_costed_from_the_pinned_rate() -> None:
    outcome = await Gateway(catalogue(), {"alpha": LiveStub()}, sleep=no_sleep).call(
        "default", system="s", user="u", output_schema=SCHEMA
    )
    assert outcome.usage.cost_usd == Decimal("0.022060")
    assert outcome.usage.price_snapshot == "test-2026-11-01"


async def test_a_fallback_served_by_an_unknown_model_says_which_rate_was_used() -> None:
    outcome = await Gateway(catalogue(), {"alpha": LiveStub(served="other-9")}, sleep=no_sleep).call(
        "default", system="s", user="u", output_schema=SCHEMA
    )
    assert outcome.usage.price_snapshot is not None and "served by other-9" in outcome.usage.price_snapshot


async def test_a_fixture_never_costs_money_or_invents_tokens() -> None:
    alpha = FakeProvider.scripted("alpha", [Reply.json({})])
    outcome = await Gateway(catalogue(), {"alpha": alpha}, sleep=no_sleep).call(
        "default", system="s", user="u", output_schema=SCHEMA
    )
    assert outcome.mode is ExecutionMode.FIXTURE
    assert (outcome.usage.cost_usd, outcome.usage.output_tokens) == (0, None)


# --- the Anthropic adapter, offline ---------------------------------------------------------------------------------


def _message(stop: str, **extra: Any) -> anthropic.types.Message:
    return anthropic.types.Message.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": '{"a": 1}'}],
            "stop_reason": stop,
            "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 3},
            **extra,
        }
    )


@pytest.mark.parametrize(
    ("stop", "mapped"),
    [
        ("end_turn", "end"),
        ("max_tokens", "truncated"),
        ("model_context_window_exceeded", "truncated"),
        ("refusal", "refused"),
    ],
)
def test_the_adapter_maps_every_stop_reason(stop: str, mapped: str) -> None:
    got = _response(_message(stop))
    assert got.stop == mapped
    assert (got.input_tokens, got.output_tokens, got.cache_read_tokens, got.cache_write_tokens) == (10, 5, 3, None)


def test_a_refusal_keeps_its_category() -> None:
    got = _response(_message("refusal", stop_details={"type": "refusal", "category": "cyber"}))
    assert (got.stop, got.refusal_category) == ("refused", "cyber")


class _RaisingMessages:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def create(self, **_: Any) -> Any:
        raise self.exc


def _status_error(cls: type[anthropic.APIStatusError], status: int, headers: dict[str, str] | None = None) -> Exception:
    request = httpx2.Request("POST", "https://api.invalid/v1/messages")
    return cls("x", response=httpx2.Response(status, headers=headers or {}, request=request), body=None)


@pytest.mark.parametrize(
    ("exc", "kind", "retryable"),
    [
        (_status_error(anthropic.RateLimitError, 429, {"retry-after": "2"}), "rate_limited", True),
        (_status_error(anthropic.AuthenticationError, 401), "auth", False),
        (_status_error(anthropic.BadRequestError, 400), "bad_request", False),
        (_status_error(anthropic.InternalServerError, 500), "unavailable", True),
    ],
)
async def test_the_adapter_classifies_failures(exc: Exception, kind: str, retryable: bool) -> None:
    provider = AnthropicProvider("anthropic", "sk-test-not-a-real-key", refusal_fallback=False)
    provider._client.messages = _RaisingMessages(exc)  # type: ignore[assignment]
    request = LLMRequest("claude-opus-5-5", "medium", "s", "u", SCHEMA, 100, 5)
    with pytest.raises(ProviderError) as caught:
        await provider.complete(request)
    assert (caught.value.kind, caught.value.retryable) == (kind, retryable)
    if kind == "rate_limited":
        assert caught.value.retry_after == 2.0
