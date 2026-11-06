"""The embeddings gateway: the one place text becomes vectors (02/B8). It implements the domain's `Embedder` port.

The catalogue names the model and its size (`embeddings.default`); together they are the embedding space each vector
records. No credential means embeddings are off: a stated mode, never an error, and search then runs lexical only
(01/R5). Batches are retried from one budget per batch, only for transient failures (01/R6, 02/I2). Any batch failing
fails the whole call, so a document is never stored half embedded.

Cost: the Gemini API returns no token counts for embeddings, so per-call cost is not recorded here (an `OPEN` gap
listed in plans/b4); the provider's bill is the record until it does.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable, Mapping, Sequence

from ..domain.retrieval import Embedded, EmbedTask
from .catalogue import Catalogue, EmbeddingModel
from .gateway import backoff_seconds
from .providers import ProviderError
from .providers.embedding import EmbeddingProvider, EmbedRequest
from .providers.gemini import GeminiEmbeddings


class Embeddings:
    def __init__(
        self,
        model: EmbeddingModel | None,
        provider: EmbeddingProvider | None,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self.model, self._provider = model, provider
        self._sleep, self._jitter = sleep, jitter

    @classmethod
    def from_environment(cls, catalogue: Catalogue, env: Mapping[str, str], use: str = "default") -> Embeddings:
        """Build the provider when its credential is set. The credential is read here and nowhere else."""
        model = catalogue.embeddings.get(use)
        if model is None:
            return cls(None, None)
        spec = catalogue.providers[model.provider]
        key = env.get(spec.credential_env or "", "")
        # The fake is never built from the environment: tests pass it in (06/T4).
        provider = GeminiEmbeddings(model.provider, key) if spec.adapter == "gemini" and key else None
        return cls(model, provider)

    @property
    def space(self) -> str | None:
        return self.model.space if self.model is not None and self._provider is not None else None

    async def embed(self, texts: Sequence[str], *, task: EmbedTask) -> Embedded:
        model, provider = self.model, self._provider
        if model is None or provider is None:
            return Embedded.off()
        vectors: list[tuple[float, ...]] = []
        attempts = 0
        for start in range(0, len(texts), model.batch_size):
            request = EmbedRequest(
                model.id, tuple(texts[start : start + model.batch_size]), task, model.dimensions, model.timeout_seconds
            )
            for attempt in range(1, model.max_attempts + 1):
                attempts += 1
                try:
                    vectors.extend(await provider.embed(request))
                    break
                except ProviderError as exc:
                    if not exc.retryable or attempt == model.max_attempts:
                        reason = {"unavailable": "provider_unavailable", "rate_limited": "rate_limited"}.get(
                            exc.kind, f"provider_{exc.kind}"
                        )
                        return Embedded(None, None, provider.mode, reason, attempts)
                    await self._sleep(backoff_seconds(attempt, exc.retry_after, self._jitter))
        return Embedded(tuple(vectors), model.space, provider.mode, None, attempts)
