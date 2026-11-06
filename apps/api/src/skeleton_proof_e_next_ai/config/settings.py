"""Process settings only (02/B5): environment, connections, file locations.

Business configuration (what varies per policy or customer) is versioned data in apps/api/config/,
loaded by persistence/business_config.py. Unknown settings raise (fail closed, 02/B7).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

API_ROOT = Path(__file__).resolve().parents[3]  # apps/api


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_file=None, extra="forbid", frozen=True)

    env: Literal["local", "test", "staging", "production"] = "local"
    build_sha: str = "unknown"
    # Where traces and metrics go over OTLP/HTTP (07/O9, 13/SK7), e.g. a collector, Langfuse or Phoenix. Unset: nowhere.
    otel_endpoint: str | None = None

    # Database: the app connects as an unprivileged role. When db_app_role is set (local and tests,
    # connecting as the owner), every transaction starts with SET LOCAL ROLE so grants and RLS apply.
    database_url: str = "postgresql+psycopg://localhost/app"
    db_app_role: str | None = "app_user"
    db_worker_role: str | None = "app_worker"
    db_pool_size: int = Field(default=5, ge=1, le=50)

    # Identity (02/Z1): tokens are verified against a pinned JWKS; with no JWKS every request is 401.
    auth_jwks_file: Path | None = None
    auth_issuer: str = "local-dev"
    auth_audience: str = "app-api"
    auth_algorithms: tuple[str, ...] = ("EdDSA", "RS256")
    # Where the tenant lives in this provider's tokens (Zitadel, Keycloak and Entra name it differently).
    auth_tenant_claim: str = "tid"
    # Privileged acts need a recent phishing-resistant sign-in (02/Z3, Z4): which `amr` values count, and how recent.
    auth_strong_amr: tuple[str, ...] = ("hwk", "swk", "pop")
    auth_step_up_seconds: int = Field(default=900, ge=60)

    # Limits (02/A13, 01/R2).
    rate_limit_store: Literal["memory", "postgres"] = "memory"
    max_page_size: int = Field(default=100, ge=1, le=1000)
    upload_dir: Path = API_ROOT / ".uploads"
    upload_max_bytes: int = Field(default=5 * 1024 * 1024, ge=1)

    business_config_dir: Path = API_ROOT / "config"
    # The governed AI's data (12/N4): the model catalogue and the agent files. Provider credentials stay in the
    # environment under the names ai/models.yaml gives them, never here (05/SG12).
    ai_dir: Path = API_ROOT.parents[1] / "ai"
    # How an approval waits for its person: LangGraph's durable checkpoints (13/SK5), or plain (the proposal row only).
    ai_workflow: Literal["langgraph", "plain"] = "langgraph"
    # Outside MCP servers (ai/mcp-servers.yaml): the key that seals each tenant's client secret, 32 random bytes in
    # base64, from the secret manager. Unset: no outside server can be connected; nothing is ever stored in clear.
    mcp_secrets_key: SecretStr | None = None
    # This product as an MCP server for outside agents (api/mcp.py). Its tokens name this audience, never the API's,
    # so a token for one is refused by the other (audience-bound, 02/Z1). Hosts guard against DNS rebinding.
    mcp_audience: str = "app-mcp"
    # Where an MCP client signs in (RFC 9728 `authorization_servers`); by default the token issuer when it is a URL.
    mcp_authorization_server: str | None = None
    mcp_resource_url: str = "http://localhost:8000/mcp"
    mcp_allowed_hosts: list[str] = ["localhost:8000", "127.0.0.1:8000"]

    # Inbound webhooks (02/I4): source -> its signing secrets (several during key rotation). A source with no secret
    # doesn't exist, so its URL answers 404. Set WEBHOOK_SECRETS as JSON in the environment, never in git.
    webhook_secrets: dict[str, list[str]] = {}
    webhook_max_bytes: int = Field(default=256 * 1024, ge=1)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
