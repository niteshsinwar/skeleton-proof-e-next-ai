"""Retrieval, offline (04/X4): chunking, fusion, the embedding catalogue and gateway, the Gemini adapter's error
mapping, and degraded search. Nothing here reaches a real model; the fake's vectors are labelled fixture (06/T4)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from google.genai import errors
from pydantic import ValidationError

from skeleton_proof_e_next_ai.domain.ai import DataClass, ExecutionMode, Trust
from skeleton_proof_e_next_ai.domain.errors import InvariantViolated
from skeleton_proof_e_next_ai.domain.retrieval import (
    Chunk,
    ChunkKey,
    Document,
    Embedded,
    EmbedTask,
    SearchHit,
    SearchScope,
)
from skeleton_proof_e_next_ai.intelligence import catalogue as cat
from skeleton_proof_e_next_ai.intelligence.embeddings import Embeddings
from skeleton_proof_e_next_ai.intelligence.providers import ProviderError
from skeleton_proof_e_next_ai.intelligence.providers.embedding import (
    EmbedRequest,
    FakeEmbeddingProvider,
)
from skeleton_proof_e_next_ai.intelligence.providers.gemini import GeminiEmbeddings
from skeleton_proof_e_next_ai.persistence.schema import EMBEDDING_DIMENSIONS
from skeleton_proof_e_next_ai.retrieval.chunking import chunk
from skeleton_proof_e_next_ai.retrieval.engine import HybridRetriever
from skeleton_proof_e_next_ai.retrieval.fusion import rrf

from .ai_support import CATALOGUE

pytestmark = pytest.mark.anyio
AI_ROOT = Path(__file__).resolve().parents[4] / "ai"
TENANT = UUID(int=10)
NOW = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)


def model(**overrides: Any) -> cat.EmbeddingModel:
    spec: dict[str, Any] = {
        "provider": "fake",
        "id": "fake-embed",
        "dimensions": 8,
        "max_input_tokens": 2048,
        "batch_size": 2,
        "price": {"snapshot": "test-2026-11-05", "input_per_mtok": "0"},
    }
    return cat.EmbeddingModel.model_validate(spec | overrides)


async def no_sleep(_: float) -> None:
    return None


# Chunking (04/X4: chunk on structure)


def test_chunks_follow_headings_and_paragraphs() -> None:
    text = "# Guide\nIntro line one.\nIntro line two.\n\n## Setup\nInstall it.\n\n## Use\nRun it.\n# Other\nMore."
    got = chunk(text)
    assert [(c.position, c.heading, c.text) for c in got] == [
        (1, "Guide", "Intro line one. Intro line two."),
        (2, "Guide > Setup", "Install it."),
        (3, "Guide > Use", "Run it."),
        (4, "Other", "More."),
    ]


def test_a_long_paragraph_splits_at_sentences_and_loses_nothing() -> None:
    sentences = [f"Sentence number {i} says something." for i in range(40)]
    got = chunk(" ".join(sentences), max_chars=200)
    assert len(got) > 1 and all(len(c.text) <= 200 for c in got)
    assert " ".join(c.text for c in got) == " ".join(sentences)
    assert all(c.text.endswith(".") for c in got)  # never cut mid-sentence when sentences fit
    assert chunk(" ".join(sentences), max_chars=200) == got  # deterministic


def test_one_sentence_longer_than_the_limit_is_cut_without_loss() -> None:
    word = "x" * 450
    got = chunk(word, max_chars=200)
    assert [len(c.text) for c in got] == [200, 200, 50] and "".join(c.text for c in got) == word


def test_blank_text_has_no_chunks() -> None:
    assert chunk("\n\n   \n# Only a heading\n") == []


# Fusion (04/X4: fuse lanes with RRF)


def test_rrf_ranks_agreement_above_one_lanes_top_result() -> None:
    fused = rrf({"lexical": ["a", "b", "c"], "vector": ["d", "b", "a"]})
    # a: 1/61 + 1/63, b: 1/62 + 1/62, d: 1/61, c: 1/63. Agreement beats either lane's top result alone.
    assert [item for item, _, _ in fused] == ["a", "b", "d", "c"]
    assert dict((i, lanes) for i, _, lanes in fused)["b"] == ("lexical", "vector")
    assert dict((i, lanes) for i, _, lanes in fused)["d"] == ("vector",)


def test_rrf_breaks_ties_by_the_first_lane_and_rank() -> None:
    fused = rrf({"lexical": ["x"], "vector": ["y"]})
    assert [i for i, _, _ in fused] == ["x", "y"] and fused[0][1] == fused[1][1]


# Catalogue (02/B5: refused at start, never on a live call)


def _with(**extra: Any) -> dict[str, Any]:
    data = {**CATALOGUE, "providers": {**CATALOGUE["providers"], "g": {"adapter": "gemini"}}}
    return data | extra


def test_an_embedding_space_names_provider_model_and_size() -> None:
    assert model().space == "fake/fake-embed@8"
    c = cat.Catalogue.model_validate(_with(embeddings={"default": model(provider="g").model_dump(mode="json")}))
    assert c.embeddings["default"].space == "g/fake-embed@8"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"embeddings": {"default": {**model().model_dump(mode="json"), "provider": "nope"}}}, "unknown provider"),
        ({"embeddings": {"default": {**model().model_dump(mode="json"), "dimensions": 3072}}}, "less than or equal"),
        ({"routes": {"default": {"model": "g-chat"}}}, "can't answer messages"),
    ],
)
def test_the_catalogue_refuses_embeddings_it_cannot_serve(change: dict[str, Any], message: str) -> None:
    data = _with(**change)
    data["models"] = {**data["models"], "g-chat": {**data["models"]["a-large"], "provider": "g"}}
    with pytest.raises(ValidationError, match=message):
        cat.Catalogue.model_validate(data)


def test_a_chat_only_provider_cannot_embed() -> None:
    data = {**CATALOGUE, "providers": {**CATALOGUE["providers"], "c": {"adapter": "anthropic"}}}
    data["embeddings"] = {"default": {**model().model_dump(mode="json"), "provider": "c"}}
    with pytest.raises(ValidationError, match="can't embed"):
        cat.Catalogue.model_validate(data)


def test_the_project_catalogue_and_the_vector_column_agree() -> None:
    project = cat.load(AI_ROOT / "models.yaml", today=date(2026, 11, 5), production=True)
    assert project.embeddings["default"].dimensions == EMBEDDING_DIMENSIONS
    assert project.providers[project.embeddings["default"].provider].adapter == "gemini"


# The embeddings gateway (01/R5 AI off is a mode; 01/R6 one retry budget)


def test_without_a_credential_embeddings_are_off() -> None:
    project = cat.load(AI_ROOT / "models.yaml", today=date(2026, 11, 5), production=False)
    off = Embeddings.from_environment(project, {})
    assert off.space is None and off.model is not None
    assert Embeddings.from_environment(project, {"GEMINI_API_KEY": "k"}).space == "gemini/gemini-embedding-001@768"


async def test_embeddings_off_return_a_stated_failure() -> None:
    got = await Embeddings(model(), None).embed(["a"], task=EmbedTask.QUERY)
    assert got.vectors is None and got.failure == "ai_off" and got.mode is ExecutionMode.AI_OFF


async def test_batches_follow_the_catalogue_and_vectors_keep_input_order() -> None:
    fake = FakeEmbeddingProvider()
    got = await Embeddings(model(), fake, sleep=no_sleep).embed(["a", "b", "c"], task=EmbedTask.DOCUMENT)
    assert [len(c.texts) for c in fake.calls] == [2, 1]
    assert got.vectors is not None and len(got.vectors) == 3 and got.space == "fake/fake-embed@8"
    assert got.mode is ExecutionMode.FIXTURE  # a fake never passes as live (06/T4)
    assert got.vectors[0] != got.vectors[1] and all(abs(sum(x * x for x in v) - 1) < 1e-9 for v in got.vectors)


async def test_a_transient_failure_is_retried_within_the_budget() -> None:
    fake = FakeEmbeddingProvider(failures=[("unavailable", True)])
    waits: list[float] = []

    async def sleep(s: float) -> None:
        waits.append(s)

    got = await Embeddings(model(), fake, sleep=sleep, jitter=lambda: 1.0).embed(["a"], task=EmbedTask.QUERY)
    assert got.vectors is not None and got.attempts == 2 and waits == [0.5]


async def test_a_permanent_failure_is_not_retried_and_nothing_half_embedded_is_returned() -> None:
    fake = FakeEmbeddingProvider(failures=[("auth", False)])
    got = await Embeddings(model(), fake, sleep=no_sleep).embed(["a", "b", "c"], task=EmbedTask.DOCUMENT)
    assert got.vectors is None and got.failure == "provider_auth" and got.attempts == 1 and len(fake.calls) == 1


async def test_a_later_batch_failing_fails_the_whole_call() -> None:
    fake = FakeEmbeddingProvider()
    embeddings = Embeddings(model(max_attempts=1), fake, sleep=no_sleep)
    fake.failures = []
    original = fake.embed

    async def second_fails(request: EmbedRequest) -> tuple[tuple[float, ...], ...]:
        if len(fake.calls) == 1:
            fake.calls.append(request)
            raise ProviderError("unavailable", "down", retryable=True)
        return await original(request)

    fake.embed = second_fails  # type: ignore[method-assign]
    got = await embeddings.embed(["a", "b", "c"], task=EmbedTask.DOCUMENT)
    assert got.vectors is None and got.failure == "provider_unavailable"


# The Gemini adapter: errors become our kinds; vectors come back unit length (13/V7)


@dataclass
class _Models:
    outcome: Any
    seen: list[dict[str, Any]] = field(default_factory=list)

    async def embed_content(self, **kw: Any) -> Any:
        self.seen.append(kw)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


@dataclass
class _Client:
    models: _Models

    @property
    def aio(self) -> _Client:
        return self


def _gemini(outcome: Any) -> tuple[GeminiEmbeddings, _Models]:
    models = _Models(outcome)
    return GeminiEmbeddings("gemini", "k", client=_Client(models)), models  # type: ignore[arg-type]


REQUEST = EmbedRequest("gemini-embedding-001", ("a", "b"), EmbedTask.QUERY, 3, 30)


def _body(code: int, status: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": status.lower(), "status": status}}


@pytest.mark.parametrize(
    ("error", "kind", "retryable"),
    [
        (errors.ClientError(429, _body(429, "RESOURCE_EXHAUSTED")), "rate_limited", True),
        (errors.ClientError(401, _body(401, "UNAUTHENTICATED")), "auth", False),
        (errors.ClientError(400, _body(400, "INVALID_ARGUMENT")), "bad_request", False),
        (errors.ServerError(503, _body(503, "UNAVAILABLE")), "unavailable", True),
    ],
)
async def test_gemini_errors_become_our_kinds(error: Exception, kind: str, retryable: bool) -> None:
    adapter, _ = _gemini(error)
    with pytest.raises(ProviderError) as caught:
        await adapter.embed(REQUEST)
    assert caught.value.kind == kind and caught.value.retryable is retryable


@dataclass
class _Embedding:
    values: list[float] | None


@dataclass
class _Response:
    embeddings: list[_Embedding]


async def test_gemini_vectors_are_normalised_and_the_request_is_shaped() -> None:
    adapter, models = _gemini(_Response([_Embedding([3.0, 0.0, 4.0]), _Embedding([0.0, 2.0, 0.0])]))
    got = await adapter.embed(REQUEST)
    assert got == ((0.6, 0.0, 0.8), (0.0, 1.0, 0.0))
    config = models.seen[0]["config"]
    assert models.seen[0]["contents"] == ["a", "b"] and config.task_type == "RETRIEVAL_QUERY"
    assert config.output_dimensionality == 3 and config.http_options.timeout == 30_000


@pytest.mark.parametrize("vectors", [[[1.0, 0.0, 0.0]], [[1.0, 0.0], [0.0, 1.0]], [[1.0, 0, 0], None]])
async def test_gemini_answers_of_the_wrong_shape_are_refused(vectors: list[Any]) -> None:
    adapter, _ = _gemini(_Response([_Embedding(v) for v in vectors]))
    with pytest.raises(ProviderError, match="wrong number or size"):
        await adapter.embed(REQUEST)


# Domain rules and degraded search


def test_documents_refuse_regulated_data_and_roles_decide_visibility() -> None:
    base: dict[str, Any] = {
        "id": UUID(int=1), "tenant_id": TENANT, "title": "Guide", "source_ref": "upload:1",
        "data_class": DataClass.INTERNAL, "allowed_roles": (), "version": 1, "created_by": "alice", "created_at": NOW,
    }  # fmt: skip
    assert Document(**base).visible_to(frozenset())
    restricted = Document(**base | {"allowed_roles": ("approver",)})
    assert restricted.visible_to(frozenset({"approver"})) and not restricted.visible_to(frozenset({"member"}))
    with pytest.raises(InvariantViolated, match="Regulated"):
        Document(**base | {"data_class": DataClass.REGULATED})


def test_an_embedding_result_has_vectors_or_a_reason() -> None:
    with pytest.raises(InvariantViolated):
        Embedded(None, None, ExecutionMode.AI_OFF, None)
    with pytest.raises(InvariantViolated):
        Embedded(((1.0,),), None, ExecutionMode.LIVE, None)


def test_a_hit_enters_a_prompt_as_untrusted_data() -> None:
    hit = SearchHit(UUID(int=1), 2, "Guide", "Setup", "Install it.", DataClass.CONFIDENTIAL, 0.1, ("lexical",))
    item = hit.as_context(TENANT)
    assert item.trust is Trust.EXTERNAL and not item.may_drive_action
    assert item.source == "document.chunk" and item.ref.endswith("#2") and item.data_class is DataClass.CONFIDENTIAL
    assert item.text == "Guide > Setup\nInstall it."


@dataclass
class _Store:
    lexical_keys: list[ChunkKey]
    vector_keys: list[ChunkKey]
    asked_space: list[str] = field(default_factory=list)

    async def add(self, document: Document, chunks: Sequence[Chunk], embedded: Embedded) -> None: ...
    async def get(self, document_id: UUID, scope: SearchScope) -> Document | None: ...
    async def delete(self, document_id: UUID) -> None: ...

    async def lexical(self, scope: SearchScope, query: str, limit: int) -> list[ChunkKey]:
        return self.lexical_keys

    async def nearest(self, scope: SearchScope, vector: Sequence[float], space: str, limit: int) -> list[ChunkKey]:
        self.asked_space.append(space)
        return self.vector_keys

    async def hits(self, scope: SearchScope, keys: Sequence[ChunkKey]) -> Mapping[ChunkKey, SearchHit]:
        return {k: SearchHit(k[0], k[1], "T", "", "x", DataClass.INTERNAL, 0.0, ()) for k in keys}


A, B = (UUID(int=1), 1), (UUID(int=2), 1)
SCOPE = SearchScope(TENANT, frozenset({"member"}))


async def test_without_a_query_vector_search_is_lexical_and_says_so() -> None:
    store = _Store([A], [B])
    got = await HybridRetriever(Embeddings(model(), None)).search(store, SCOPE, "q", Embedded.off(), 5)
    assert got.lanes == ("lexical",) and got.degraded == "vector lane off: ai_off"
    assert [(h.document_id, h.lanes) for h in got.hits] == [(A[0], ("lexical",))] and store.asked_space == []


async def test_with_a_query_vector_both_lanes_run_in_its_space() -> None:
    store = _Store([A, B], [B])
    vector = Embedded(((1.0,) * 8,), "fake/fake-embed@8", ExecutionMode.FIXTURE)
    got = await HybridRetriever(Embeddings(model(), None)).search(store, SCOPE, "q", vector, 5)
    assert got.lanes == ("lexical", "vector") and got.degraded is None and store.asked_space == ["fake/fake-embed@8"]
    assert [h.document_id for h in got.hits] == [B[0], A[0]] and got.hits[0].lanes == ("lexical", "vector")
