"""Gemini embeddings behind the embedding port (13/V7). Read against google-genai 2.33.0 as installed (2026-11-05).

- One call embeds one batch: `client.aio.models.embed_content(model=, contents=[...], config=EmbedContentConfig(...))`,
  answering `embeddings[i].values` in input order.
- The SDK's own retries are switched off (`HttpRetryOptions(attempts=1)`) so the gateway's single budget is the only
  one (01/R6). Its timeout is in milliseconds.
- `gemini-embedding-001` returns unit vectors only at its full 3072 dimensions; smaller sizes are normalised here.
- `auto_truncate` is refused by the Gemini API (the SDK raises), so over-long input is kept out by the chunker's limit.
"""

from __future__ import annotations

import httpx
from google import genai
from google.genai import errors, types

from ...domain.ai import ExecutionMode
from ...domain.retrieval import EmbedTask
from . import ProviderError
from .embedding import EmbedRequest, normalise

TASK_TYPES = {EmbedTask.DOCUMENT: "RETRIEVAL_DOCUMENT", EmbedTask.QUERY: "RETRIEVAL_QUERY"}


class GeminiEmbeddings:
    def __init__(self, name: str, api_key: str, *, client: genai.Client | None = None) -> None:
        self.name = name
        self._client = client or genai.Client(
            api_key=api_key, http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1))
        )

    @property
    def mode(self) -> ExecutionMode:
        return ExecutionMode.LIVE

    async def embed(self, request: EmbedRequest) -> tuple[tuple[float, ...], ...]:
        config = types.EmbedContentConfig(
            task_type=TASK_TYPES[request.task],
            output_dimensionality=request.dimensions,
            http_options=types.HttpOptions(timeout=int(request.timeout_seconds * 1000)),
        )
        try:
            response = await self._client.aio.models.embed_content(
                model=request.model_id, contents=list(request.texts), config=config
            )
        except errors.ClientError as exc:
            if exc.code == 429:  # a per-minute limit and an exhausted quota look alike here; the budget bounds both
                raise ProviderError("rate_limited", "rate limited", retryable=True) from exc
            if exc.code in (401, 403):
                raise ProviderError("auth", "credential refused", retryable=False) from exc
            raise ProviderError("bad_request", f"request refused ({exc.code})", retryable=False) from exc
        except errors.ServerError as exc:
            raise ProviderError("unavailable", f"provider error ({exc.code})", retryable=True) from exc
        except errors.APIError as exc:
            raise ProviderError("provider_error", f"status {exc.code}", retryable=False) from exc
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise ProviderError("unavailable", "timed out or unreachable", retryable=True) from exc
        vectors = [e.values for e in response.embeddings or []]
        if len(vectors) != len(request.texts) or any(v is None or len(v) != request.dimensions for v in vectors):
            raise ProviderError("provider_error", "embeddings came back in the wrong number or size", retryable=False)
        return tuple(normalise(v) for v in vectors if v is not None)
