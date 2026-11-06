"""Outside tools (04/K3, 05/SG5): tools on other systems' MCP servers, offered to agents only as a person reviewed them.

A tool's contract is its description and its input schema. The reviewed copy lives in `ai/mcp-servers.yaml`; the live
copy is checked against it on every call, by fingerprint, so a server that changes what a tool says or takes
(tool poisoning, a rug pull) is refused until someone reviews the change. Results are external text: data for the
model, never instructions. A write on another system is always a proposal a person decides (04/K1).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from .ai import ToolKind


def fingerprint(description: str, input_schema: Mapping[str, Any]) -> str:
    contract = {"description": description, "input_schema": input_schema}
    canonical = json.dumps(contract, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class OutsideTool:
    server: str
    name: str
    kind: ToolKind
    description: str
    input_schema: Mapping[str, Any]

    @property
    def key(self) -> str:
        """The name agents use: `<server>__<tool>` (provider tool names allow letters, digits, `_` and `-`)."""
        return f"{self.server}__{self.name}"

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.description, self.input_schema)


@dataclass(frozen=True, slots=True)
class Credentials:
    """An OAuth client registered with an outside server for one tenant (client_credentials grant)."""

    client_id: str
    client_secret: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class Connection:
    server: str
    client_id: str
    connected_by: str
    connected_at: datetime


@dataclass(frozen=True, slots=True)
class Drift:
    tool: str
    reason: Literal["changed", "missing", "unreviewed"]
