"""Domain errors: expected problems the API turns into RFC 9457 responses (02/A6, 02/A7)."""

from __future__ import annotations


class DomainError(Exception):
    """Base class. `code` is stable and documented; `detail` must be safe to show a user."""

    code = "domain-error"
    status = 422

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class InvariantViolated(DomainError):
    code = "invariant-violated"
    status = 422


class IllegalTransition(DomainError):
    code = "illegal-transition"
    status = 409

    def __init__(self, detail: str, legal: list[str]) -> None:
        super().__init__(detail)
        self.legal = legal


class NotFound(DomainError):
    """Also used when the caller may not see the object: 404 for both, with the same body (02/A7)."""

    code = "not-found"
    status = 404


class Forbidden(DomainError):
    code = "forbidden"
    status = 403


class StepUpRequired(Forbidden):
    """The act needs a recent sign-in with a phishing-resistant method (02/Z3, Z4); the UI asks for a fresh sign-in."""

    code = "step-up-required"


class VersionMismatch(DomainError):
    code = "version-mismatch"
    status = 412


class IdempotencyConflict(DomainError):
    code = "idempotency-key-reused"
    status = 422


class FeatureDisabled(DomainError):
    code = "feature-disabled"
    status = 503
