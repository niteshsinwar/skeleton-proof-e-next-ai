# MCP Python SDK (verified 2026-11-05)

What the switchboard relies on. Re-verify within 21 days of relying on it again (10/H17, H20).

| Fact | Status | Source |
|---|---|---|
| `mcp` 2.3.0 (with `mcp-types` 2.3.0, `httpx2` 2.16.0, `jsonschema` 4.26.0) resolves under the 7-day cooldown (cutoff 2026-10-28) | READ | `uv lock` under `exclude-newer` |
| `mcp.Client(server, cache=None)` takes a URL, a transport, or an in-process `MCPServer` (used by the tests); `list_tools(cursor=)` pages with `next_cursor`; `call_tool(name, arguments, read_timeout_seconds=)` answers `CallToolResult` with `is_error`, `content` and `structured_content` | READ | installed `mcp/client/client.py`, `mcp_types/_types.py`; probed in process |
| `streamable_http_client(url, http_client=httpx2.AsyncClient(...))` carries our auth and timeouts; redirects are followed only within the origin | READ | installed `mcp/client/streamable_http.py` |
| `ClientCredentialsOAuthProvider(server_url, storage, client_id, client_secret, scope=, issuer=)` runs the client_credentials grant; `storage` is the SDK's `TokenStorage` (get/set tokens and client info). With `issuer` set, token requests are built only from metadata for that issuer; omitting it warns (`MCPDeprecationWarning`, required in 3.0) and lets the MCP server choose where the client secret goes, so our loader requires it | READ | installed `mcp/client/auth/extensions/client_credentials.py` (`_checked_issuer`, `_require_metadata_for_configured_issuer`), `oauth2.py` |
| OAuth failures raise `OAuthFlowError` (`OAuthTokenError`, `OAuthRegistrationError`); server errors `MCPError` | READ | installed `mcp/client/auth/exceptions.py`, `mcp/shared/exceptions.py` |
| `MCPServer(name, token_verifier=, auth=AuthSettings(issuer_url, resource_server_url, required_scopes, validate_token_resource=))`; `streamable_http_app(stateless_http=, json_response=, transport_security=)` serves `/mcp` and `/.well-known/oauth-protected-resource/mcp`; its `session_manager.run()` must be running | READ | installed `mcp/server/mcpserver/server.py`, `auth/settings.py`; probed over ASGI |
| A call without a valid token gets 401 with `WWW-Authenticate: Bearer ... resource_metadata="<url>"`; a token missing a required scope gets 403 | READ | probed over ASGI; the integration tests |
| The Host header is checked (DNS rebinding) against `TransportSecuritySettings.allowed_hosts`; the default allows only 127.0.0.1 | READ | installed `mcp/server/transport_security.py`; probed (421 otherwise) |
| `get_access_token()` gives the verified `AccessToken` inside a tool | READ | installed `mcp/server/auth/middleware/auth_context.py` |
