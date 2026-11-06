"""Retrieval on real Postgres and pgvector, through the API (04/X4, 02/Z11, 02/D8, 02/A7).

Without a Gemini key the app's search is lexical only and says so; with the labelled fake embedder both lanes run.
The fake proves plumbing, not search quality, which only a retrieval eval on a real corpus can show (06/T4).
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import create_engine, text

from skeleton_proof_e_next_ai.intelligence.catalogue import EmbeddingModel, EmbeddingPrice
from skeleton_proof_e_next_ai.intelligence.embeddings import Embeddings
from skeleton_proof_e_next_ai.intelligence.providers.embedding import FakeEmbeddingProvider
from skeleton_proof_e_next_ai.persistence.schema import EMBEDDING_DIMENSIONS
from skeleton_proof_e_next_ai.retrieval.engine import HybridRetriever

from ..conftest import TENANT_B, auth

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

GUIDE = "# Returns\nCustomers may return goods within thirty days.\n\n# Shipping\nParcels leave the warehouse daily."
SECRET = "# Salaries\nThe salary bands are reviewed every spring."


def _fake(app: Any, model_id: str = "fake-embed") -> None:
    model = EmbeddingModel(
        provider="fake", id=model_id, dimensions=EMBEDDING_DIMENSIONS, max_input_tokens=2048,
        price=EmbeddingPrice(snapshot="test", input_per_mtok=Decimal(0)),
    )  # fmt: skip
    app.state.core.retriever = HybridRetriever(Embeddings(model, FakeEmbeddingProvider()))


async def _add(client: httpx.AsyncClient, token: str, title: str, body: str, **extra: Any) -> httpx.Response:
    payload = {"title": title, "text": body, "source_ref": f"test:{title}"} | extra
    return await client.post("/documents", json=payload, headers=auth(token))


async def _search(client: httpx.AsyncClient, token: str, query: str) -> dict[str, Any]:
    r = await client.post("/documents/search", json={"query": query}, headers=auth(token))
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


@pytest.mark.covers("POST /documents")
@pytest.mark.covers("POST /documents/search")
async def test_documents_are_found_by_words_and_by_vector(
    app_and_client: tuple[Any, httpx.AsyncClient], user: Callable[..., str]
) -> None:
    app, client = app_and_client
    _fake(app)
    admin, member = user("ada", ["admin"]), user("mo", ["member"])
    added = await _add(client, admin, "Policy", GUIDE)
    assert added.status_code == 201 and added.json()["chunks"] == 2
    assert added.json()["embedding_space"] == f"fake/fake-embed@{EMBEDDING_DIMENSIONS}"
    found = await _search(client, member, "return goods")
    assert found["lanes"] == ["lexical", "vector"] and found["degraded"] is None
    top = found["hits"][0]
    assert top["heading"] == "Returns" and top["lanes"] == ["lexical", "vector"] and top["title"] == "Policy"


async def test_without_embeddings_search_is_lexical_and_says_so(
    client: httpx.AsyncClient, user: Callable[..., str]
) -> None:
    admin = user("ada", ["admin"])
    added = await _add(client, admin, "Shipping note", GUIDE)
    assert added.status_code == 201 and added.json()["embedding_space"] is None  # stored, not embedded
    found = await _search(client, admin, "warehouse")
    assert found["lanes"] == ["lexical"] and found["degraded"] == "vector lane off: ai_off"
    assert any(h["heading"] == "Shipping" for h in found["hits"])


async def test_restricted_documents_are_never_candidates_for_other_roles(
    app_and_client: tuple[Any, httpx.AsyncClient], user: Callable[..., str]
) -> None:
    app, client = app_and_client
    _fake(app)
    admin, member, approver = user("ada", ["admin"]), user("mo", ["member"]), user("ap", ["approver"])
    assert (await _add(client, admin, "Pay", SECRET, allowed_roles=["approver"])).status_code == 201
    # Filtered before ranking: not even the vector lane, which always returns its nearest, offers it.
    assert [h for h in (await _search(client, member, "salary bands"))["hits"] if h["title"] == "Pay"] == []
    assert any(h["title"] == "Pay" for h in (await _search(client, approver, "salary bands"))["hits"])


async def test_another_tenant_finds_nothing(
    app_and_client: tuple[Any, httpx.AsyncClient], user: Callable[..., str]
) -> None:
    app, client = app_and_client
    _fake(app)
    assert (await _add(client, user("ada", ["admin"]), "Tenant A only", SECRET)).status_code == 201
    other = user("bo", ["member"], tenant=TENANT_B)
    hits = (await _search(client, other, "salary bands"))["hits"]
    assert [h for h in hits if h["title"] == "Tenant A only"] == []


async def test_vectors_from_another_space_are_never_compared(
    app_and_client: tuple[Any, httpx.AsyncClient], user: Callable[..., str]
) -> None:
    app, client = app_and_client
    _fake(app, "old-model")
    admin = user("ada", ["admin"])
    assert (await _add(client, admin, "Old space", "# Zebra\nStriped animals graze.")).status_code == 201
    _fake(app, "new-model")  # the catalogue moved on; the old vectors wait for a re-index (04/X4)
    hits = [h for h in (await _search(client, admin, "zebra"))["hits"] if h["title"] == "Old space"]
    assert hits and [h["lanes"] for h in hits] == [["lexical"]] * len(hits)


@pytest.mark.covers("DELETE /documents/{document_id}")
async def test_removing_a_document_erases_its_chunks_and_vectors(
    app_and_client: tuple[Any, httpx.AsyncClient], user: Callable[..., str], migrated: str
) -> None:
    app, client = app_and_client
    _fake(app)
    admin = user("ada", ["admin"])
    doc = (await _add(client, admin, "To erase", "# Gone\nThis text is erased.")).json()["id"]
    assert (await client.delete(f"/documents/{doc}", headers=auth(admin))).status_code == 204
    engine = create_engine(migrated)
    with engine.connect() as conn:
        left = conn.execute(text("SELECT count(*) FROM rag.chunks WHERE document_id = CAST(:d AS uuid)"), {"d": doc})
        assert left.scalar_one() == 0
        audit = conn.execute(
            text("SELECT action FROM audit.events WHERE entity_id = :d ORDER BY at, id"), {"d": doc}
        ).scalars()
        assert list(audit) == ["document.added", "document.removed"]
    engine.dispose()
    assert (await client.delete(f"/documents/{doc}", headers=auth(admin))).status_code == 404


@pytest.mark.parametrize(
    ("roles", "payload", "status"),
    [
        (["member"], {}, 403),  # searching is not managing
        (["admin"], {"allowed_roles": ["nobody"]}, 422),  # a role that doesn't exist
        (["admin"], {"data_class": "regulated"}, 422),  # never indexed without an ADR (05/SG9)
    ],
)
async def test_adding_is_refused_when_it_should_be(
    client: httpx.AsyncClient, user: Callable[..., str], roles: list[str], payload: dict[str, Any], status: int
) -> None:
    r = await _add(client, user("x", roles), "Refused", GUIDE, **payload)
    assert r.status_code == status, r.text
    restricted = await _add(client, user("ada", ["admin"]), "Allowed", GUIDE, allowed_roles=["approver"])
    assert restricted.status_code == 201  # the positive pair: a real role is accepted
