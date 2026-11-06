"""Verify, never mint (02/Z1): bearer tokens checked against a pinned JWKS.

Algorithm allowlist, required iss/aud/exp/sub, no bypass flag: with no JWKS configured every request is 401.
The token proves identity only: roles are held by the API and loaded per call (api/deps.py, 02/Z4, Z5), so a
`roles` claim is ignored. Claims map to a Principal (02/Z7): `act` (RFC 8693) marks an agent acting for the
token's subject;
`kind: service` marks a service principal; `scope` limits agents and services.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import jwt

from ..config.project import DEFAULT_TENANT, MULTI_TENANT
from ..domain.principals import Principal, PrincipalKind
from .errors import ProblemError

UNAUTHORISED = {"WWW-Authenticate": 'Bearer realm="api"'}
# RFC 8176 methods that resist phishing: hardware key, software key, proof of possession (passkeys report these).
STRONG_AMR = ("hwk", "swk", "pop")


def _deny(detail: str) -> ProblemError:
    return ProblemError(401, "unauthenticated", detail, UNAUTHORISED)


@dataclass(frozen=True, slots=True)
class VerifiedToken:
    """A token whose signature and claims passed. Whether its session was revoked is checked by the caller (deps)."""

    principal: Principal
    sha256: str  # the revoked-token list keys on this, never on the token itself
    expires_at: datetime


class TokenVerifier:
    def __init__(
        self,
        jwks: dict[str, Any] | None,
        issuer: str,
        audience: str,
        algorithms: tuple[str, ...],
        tenant_claim: str = "tid",
        strong_amr: tuple[str, ...] = STRONG_AMR,
        step_up_seconds: int = 900,
    ) -> None:
        self._keys = jwt.PyJWKSet.from_dict(jwks) if jwks else None
        self.issuer, self.audience, self.algorithms = issuer, audience, list(algorithms)
        self.tenant_claim, self.strong_amr, self.step_up_seconds = tenant_claim, frozenset(strong_amr), step_up_seconds

    @classmethod
    def from_file(
        cls, path: Path | None, issuer: str, audience: str, algorithms: tuple[str, ...], **policy: Any
    ) -> TokenVerifier:
        jwks = json.loads(path.read_text()) if path and path.is_file() else None
        return cls(jwks, issuer, audience, algorithms, **policy)

    def _stepped_up(self, claims: dict[str, Any]) -> bool:
        """A phishing-resistant method (RFC 8176 `amr`) used within the step-up window (`auth_time`, 02/Z3, Z4)."""
        amr = claims.get("amr")
        methods = {str(m) for m in amr} if isinstance(amr, list) else set()
        auth_time = claims.get("auth_time")
        if not (methods & self.strong_amr) or not isinstance(auth_time, int | float):
            return False
        return 0 <= datetime.now(UTC).timestamp() - auth_time <= self.step_up_seconds

    def verify(self, authorization: str | None) -> VerifiedToken:
        if self._keys is None:
            raise _deny("Authentication is not configured.")
        if not authorization or not authorization.lower().startswith("bearer "):
            raise _deny("A bearer token is required.")
        token = authorization[7:].strip()
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") not in self.algorithms:
                raise _deny("Token algorithm not accepted.")
            key = self._keys[header["kid"]]
            claims = jwt.decode(
                token,
                key=key.key,
                algorithms=self.algorithms,
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except ProblemError:
            raise
        except (jwt.PyJWTError, KeyError, ValueError) as exc:
            raise _deny("The token is not valid.") from exc
        principal = replace(to_principal(claims, self.tenant_claim), stepped_up=self._stepped_up(claims))
        return VerifiedToken(
            principal=principal,
            sha256=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=datetime.fromtimestamp(int(claims["exp"]), UTC),
        )


def to_principal(claims: dict[str, Any], tenant_claim: str = "tid") -> Principal:
    if MULTI_TENANT:
        if tenant_claim not in claims:
            raise _deny("The token carries no tenant.")
        try:
            tenant = UUID(str(claims[tenant_claim]))
        except ValueError as exc:
            raise _deny("The token's tenant is malformed.") from exc
    else:
        tenant = DEFAULT_TENANT
    roles: frozenset[str] = frozenset()  # filled from the grants table, never from the token
    # The display name of the person the token is about (`sub`; for an agent, the user it acts for), so screens show
    # names, never subjects (03/F16). A provider must be configured to put `name` in access tokens.
    raw_name = claims.get("name")
    name = raw_name.strip()[:200] or None if isinstance(raw_name, str) else None
    scopes = frozenset(str(claims["scope"]).split()) if "scope" in claims else None
    act = claims.get("act")
    if isinstance(act, dict) and act.get("sub"):
        return Principal(
            subject=str(act["sub"]),
            kind=PrincipalKind.AGENT,
            tenant_id=tenant,
            roles=roles,
            scopes=scopes or frozenset(),
            on_behalf_of=str(claims["sub"]),
            name=name,
        )
    if claims.get("kind") == "service":
        return Principal(
            subject=str(claims["sub"]),
            kind=PrincipalKind.SERVICE,
            tenant_id=tenant,
            roles=roles,
            scopes=scopes or frozenset(),
            name=name,
        )
    # A person's scopes are kept but never narrow them; they matter where a person's client acts for them (api/mcp.py).
    return Principal(
        subject=str(claims["sub"]), kind=PrincipalKind.HUMAN, tenant_id=tenant, roles=roles, scopes=scopes, name=name
    )
