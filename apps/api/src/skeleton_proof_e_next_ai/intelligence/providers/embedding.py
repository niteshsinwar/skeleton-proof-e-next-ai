"""The embedding provider port, and its labelled fake (02/B3, 06/T4).

An adapter makes one call for one batch and translates errors into `ProviderError`; retries and the batch loop live in
`intelligence/embeddings.py`, inside one budget, as they do for messages.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from ...domain.ai import ExecutionMode
from ...domain.retrieval import EmbedTask
from . import ErrorKind, ProviderError

WORD = re.compile(r"\w+")


@dataclass(frozen=True, slots=True)
class EmbedRequest:
    model_id: str
    texts: tuple[str, ...]
    task: EmbedTask
    dimensions: int
    timeout_seconds: float


class EmbeddingProvider(Protocol):
    name: str

    @property
    def mode(self) -> ExecutionMode: ...

    async def embed(self, request: EmbedRequest) -> tuple[tuple[float, ...], ...]: ...


def normalise(vector: Sequence[float]) -> tuple[float, ...]:
    """Unit length, so cosine distance means the same at every size. A zero vector is refused, never divided by."""
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0:
        raise ProviderError("provider_error", "the provider returned a zero vector", retryable=False)
    return tuple(x / norm for x in vector)


@dataclass
class FakeEmbeddingProvider:
    """Deterministic word hashing: texts that share words land close together, so search plumbing can be proved
    end to end. It proves plumbing, never quality; its vectors are labelled `fixture` (06/T4).

    Script failures with `failures`, one per call, before it starts answering.
    """

    name: str = "fake"
    failures: list[tuple[ErrorKind, bool]] = field(default_factory=list)  # (kind, retryable)
    calls: list[EmbedRequest] = field(default_factory=list)

    @property
    def mode(self) -> ExecutionMode:
        return ExecutionMode.FIXTURE

    async def embed(self, request: EmbedRequest) -> tuple[tuple[float, ...], ...]:
        self.calls.append(request)
        if self.failures:
            kind, retryable = self.failures.pop(0)
            raise ProviderError(kind, "scripted failure", retryable=retryable)
        return tuple(_hashed(text, request.dimensions) for text in request.texts)


def _hashed(text: str, dimensions: int) -> tuple[float, ...]:
    vector = [0.0] * dimensions
    for word in WORD.findall(text.lower()):
        digest = hashlib.sha256(word.encode()).digest()
        vector[int.from_bytes(digest[:4], "big") % dimensions] += 1.0 if digest[4] % 2 else -1.0
    if not any(vector):
        vector[0] = 1.0
    return normalise(vector)
