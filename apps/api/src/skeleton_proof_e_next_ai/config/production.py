"""What makes a staging or production configuration unsafe (07/O4, README #6). Checked at start and by
`run.py config-check`, so a deploy with a development setting refuses to start instead of running quietly wrong.

Pure: it reads the settings and the files they name, never the network or the database.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from .project import TIER
from .settings import Settings

DEPLOYED = ("staging", "production")
# JWK members that only a private key has (RFC 7517/7518): the API verifies tokens, it never holds a signing key.
PRIVATE_MEMBERS = {"d", "p", "q", "dp", "dq", "qi", "k", "oth"}
SHA = re.compile(r"^[0-9a-f]{7,40}$")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _https(url: str | None) -> bool:
    parsed = urlparse(url or "")
    return parsed.scheme == "https" and bool(parsed.hostname) and parsed.hostname not in LOCAL_HOSTS


def _identity(settings: Settings) -> list[str]:
    found = []
    if settings.auth_jwks_file is None or not settings.auth_jwks_file.is_file():
        return ["APP_AUTH_JWKS_FILE names no file: every request would be 401 (02/Z1)"]
    try:
        keys = json.loads(settings.auth_jwks_file.read_text(encoding="utf-8")).get("keys", [])
    except ValueError, AttributeError:
        keys = None
    if not isinstance(keys, list) or not keys:
        found.append("APP_AUTH_JWKS_FILE holds no keys (02/Z1)")
    elif any(isinstance(k, dict) and PRIVATE_MEMBERS & k.keys() for k in keys):
        found.append("APP_AUTH_JWKS_FILE holds a private key: the API verifies, it never mints (02/Z1, 07/O4)")
    return found


def _mcp_server(settings: Settings) -> list[str]:
    found = []
    if not _https(settings.mcp_resource_url):
        found.append("APP_MCP_RESOURCE_URL must be this server's https URL (RFC 9728)")
    if any(host.split(":")[0] in LOCAL_HOSTS for host in settings.mcp_allowed_hosts):
        found.append("APP_MCP_ALLOWED_HOSTS still lists a local host")
    return found


def problems(settings: Settings) -> list[str]:
    """Every reason this configuration must not serve staging or production traffic; empty when it may."""
    if settings.env not in DEPLOYED:
        return []
    found: list[str] = []
    if not SHA.match(settings.build_sha):
        found.append(f"APP_BUILD_SHA is {settings.build_sha!r}: a deployed build shows its git SHA (02/A12)")
    found += _identity(settings)
    if not _https(settings.auth_issuer):
        found.append(f"APP_AUTH_ISSUER is {settings.auth_issuer!r}: a deployed API trusts only an https issuer")
    if TIER != "P" and settings.rate_limit_store == "memory":
        found.append("APP_RATE_LIMIT_STORE is memory: from tier S, instances share limits (01/R2, 01/AL2)")
    found += _mcp_server(settings)
    if settings.upload_dir.resolve().is_relative_to(settings.business_config_dir.parent.resolve()):
        found.append("APP_UPLOAD_DIR is inside the source tree, so uploads are lost with the image: mount a volume")
    return found
