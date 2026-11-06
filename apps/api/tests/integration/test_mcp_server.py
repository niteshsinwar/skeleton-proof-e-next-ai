"""This product as an MCP server, over real HTTP through the app (04/K3, 02/Z1, RFC 9728).

Tokens are audience-bound both ways; a call without one points the client at the protected-resource metadata; an
agent sees only what its person may see (02/A7); a person's MCP client acts for them, never as them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from ..conftest import auth

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

BASE = "http://localhost:8000"  # an allowed host (DNS rebinding guard)


@pytest.fixture
async def served(app_and_client: tuple[Any, httpx.AsyncClient]) -> AsyncIterator[Any]:
    app, _ = app_and_client
    async with app.router.lifespan_context(app):  # runs the MCP session manager
        yield app


def _http(app: Any, token: str | None = None) -> httpx2.AsyncClient:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE, headers=headers)


async def _call(app: Any, token: str, name: str, arguments: dict[str, Any]) -> Any:
    async with _http(app, token) as h, Client(streamable_http_client(f"{BASE}/mcp", http_client=h), cache=None) as c:
        return await c.call_tool(name, arguments)


async def test_the_metadata_names_where_to_sign_in(served: Any) -> None:
    async with _http(served) as h:
        meta = (await h.get("/.well-known/oauth-protected-resource/mcp")).json()
        challenge = await h.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert meta["resource"] == f"{BASE}/mcp" and meta["scopes_supported"] == ["mcp"] and meta["authorization_servers"]
    assert challenge.status_code == 401
    assert (
        'resource_metadata="http://localhost:8000/.well-known/oauth-protected-resource/mcp"'
        in challenge.headers["www-authenticate"]
    )


async def test_tokens_are_bound_to_their_audience_both_ways(
    served: Any, client: httpx.AsyncClient, make_token: Callable[..., str], user: Callable[..., str]
) -> None:
    user("alice", ["member"])
    api_token = make_token("alice", act="agent-1", scope="mcp")
    async with _http(served, api_token) as h:
        r = await h.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 401  # an API token is not an MCP token
    mcp_token = make_token("alice", aud="app-mcp", scope="mcp")
    assert (await client.get("/work-items", headers=auth(mcp_token))).status_code == 401  # nor the reverse


async def test_an_agent_reads_its_persons_work_item_and_nobody_elses(
    served: Any, client: httpx.AsyncClient, make_token: Callable[..., str], user: Callable[..., str]
) -> None:
    alice, bob = user("alice", ["member"]), user("bob", ["member"])
    mine = (await client.post("/work-items", json={"title": "Alice's item"}, headers=auth(alice))).json()["id"]
    theirs = (await client.post("/work-items", json={"title": "Bob's item"}, headers=auth(bob))).json()["id"]
    agent = make_token("alice", aud="app-mcp", act="agent-1", scope="mcp")
    got = await _call(served, agent, "get_work_item", {"item_id": mine})
    assert not got.is_error and got.structured_content == {"id": mine, "title": "Alice's item", "state": "draft"}
    hidden = await _call(served, agent, "get_work_item", {"item_id": theirs})
    assert hidden.is_error and "No such work item" in hidden.content[0].text  # BOLA: like it doesn't exist


async def test_a_persons_mcp_client_acts_for_them_and_a_token_needs_the_mcp_scope(
    served: Any, client: httpx.AsyncClient, make_token: Callable[..., str], user: Callable[..., str]
) -> None:
    alice = user("alice", ["member"])
    mine = (await client.post("/work-items", json={"title": "Via a desktop client"}, headers=auth(alice))).json()["id"]
    as_person = make_token("alice", aud="app-mcp", scope="mcp")  # no `act`: an MCP client signed in as alice
    assert not (await _call(served, as_person, "get_work_item", {"item_id": mine})).is_error
    no_scope = make_token("alice", aud="app-mcp", act="agent-1", scope="work_item.create")
    async with _http(served, no_scope) as h:
        r = await h.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 403
