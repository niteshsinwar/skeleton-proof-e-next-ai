"""Facts fixed when the project was rendered from the skeleton. Changing tenancy is an ADR and a migration (02/Z9)."""

from __future__ import annotations

from uuid import UUID

PROJECT_NAME = "skeleton proof e next ai"
# The name this code reports in traces and metrics (07/O9): one per process role.
SERVICE = "skeleton-proof-e-next-ai"
MULTI_TENANT = True
# The tier (01/S1): it decides how strict deployment is (e.g. shared rate limits from tier S, 01/AL2).
TIER = "E"
# Single-tenant projects still carry tenant_id on every row, so moving to multi-tenant later is a policy
# change, not a rewrite. Every row uses this tenant.
DEFAULT_TENANT = UUID(int=0)
