"""Anthropic adapter (13/V7), on the official SDK read from its installed source (anthropic 2.3.0, 10/H20; the dated
note is `.claude/reference/anthropic-sdk.md`).

One call, no retries of its own (`max_retries=0`): the gateway spends retries from one budget (01/R6). Output is
constrained to the step's JSON Schema (`output_config.format`) and validated again by the step runner (04/Q4). The
policy text is the cached prefix (04/X2). With the refusal fallback on, a policy decline is retried by the provider on
another model inside the same call, and the model that answered is returned (plans/b4 D4).
"""

from __future__ import annotations

from typing import Any, Literal

import anthropic
from anthropic.types import Message
from anthropic.types.beta import BetaMessage

from ...domain.ai import ExecutionMode
from . import LLMRequest, LLMResponse, ProviderError, Stop

FALLBACK_BETA: Literal["server-side-fallback-2026-07-01"] = "server-side-fallback-2026-07-01"
Effort = Literal["low", "medium", "high", "xhigh", "max"]
EFFORTS: tuple[Effort, ...] = ("low", "medium", "high", "xhigh", "max")


class AnthropicProvider:
    mode = ExecutionMode.LIVE

    def __init__(self, name: str, api_key: str, *, refusal_fallback: bool) -> None:
        if not api_key:
            raise ValueError("an API key is required; without one the gateway runs with AI off")
        self.name = name
        self._fallback = refusal_fallback
        # The key is passed explicitly so the SDK never falls back to another credential on this machine.
        self._client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=0)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        effort = _effort(request.effort)
        system: Any = [{"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}]
        messages: Any = [{"role": "user", "content": request.user}]
        output_config: Any = {
            "effort": effort,
            "format": {"type": "json_schema", "schema": dict(request.output_schema)},
        }
        try:
            message: Message | BetaMessage
            if self._fallback:
                message = await self._client.beta.messages.create(
                    model=request.model_id,
                    max_tokens=request.max_output_tokens,
                    system=system,
                    messages=messages,
                    output_config=output_config,
                    betas=[FALLBACK_BETA],
                    fallbacks="default",
                    timeout=request.timeout_seconds,
                )
            else:
                message = await self._client.messages.create(
                    model=request.model_id,
                    max_tokens=request.max_output_tokens,
                    system=system,
                    messages=messages,
                    output_config=output_config,
                    timeout=request.timeout_seconds,
                )
        except anthropic.APITimeoutError as exc:
            raise ProviderError("unavailable", "timed out", retryable=True) from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError("unavailable", "connection failed", retryable=True) from exc
        except anthropic.RateLimitError as exc:
            raise ProviderError("rate_limited", "rate limited", retryable=True, retry_after=_retry_after(exc)) from exc
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            raise ProviderError("auth", "credential refused", retryable=False) from exc
        except (anthropic.BadRequestError, anthropic.UnprocessableEntityError, anthropic.NotFoundError) as exc:
            # Includes an exhausted credit balance: not transient, so it is never retried (Aegis H).
            raise ProviderError("bad_request", f"request refused ({exc.status_code})", retryable=False) from exc
        except (
            anthropic.OverloadedError,
            anthropic.ServiceUnavailableError,
            anthropic.InternalServerError,
            anthropic.DeadlineExceededError,
        ) as exc:
            raise ProviderError("unavailable", f"provider error ({exc.status_code})", retryable=True) from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError("provider_error", f"status {exc.status_code}", retryable=False) from exc
        return _response(message)


def _effort(value: str) -> Effort:
    for e in EFFORTS:
        if e == value:
            return e
    raise ProviderError("bad_request", f"unknown effort {value!r}", retryable=False)


def _retry_after(exc: anthropic.APIStatusError) -> float | None:
    raw = exc.response.headers.get("retry-after")
    try:
        return float(raw) if raw is not None else None
    except ValueError:
        return None


def _response(message: Message | BetaMessage) -> LLMResponse:
    stop: Stop
    if message.stop_reason == "end_turn":
        stop = "end"
    elif message.stop_reason in ("max_tokens", "model_context_window_exceeded"):
        stop = "truncated"
    elif message.stop_reason == "refusal":
        stop = "refused"
    else:
        stop = "other"
    text = "".join(block.text for block in message.content if block.type == "text") or None
    usage = message.usage
    return LLMResponse(
        text=text,
        stop=stop,
        served_model=str(message.model),
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_input_tokens,
        cache_write_tokens=usage.cache_creation_input_tokens,
        refusal_category=message.stop_details.category if message.stop_details else None,
    )
