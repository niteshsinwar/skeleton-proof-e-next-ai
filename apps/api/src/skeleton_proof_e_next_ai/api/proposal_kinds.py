"""The project's proposal kinds (README #9): kind -> a factory that builds its executor on the request's connection.

An executor has `precheck` (re-validate live state just before running; a reason refuses) and `execute` (do the write
through an existing use case, so its own rules and audit apply). Nothing is registered by default: a proposal of an
unregistered kind is refused when an agent proposes it. `/ai-step` adds one with its tests.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncConnection

from ..domain.ports import ProposalExecutor

ExecutorFactory = Callable[[AsyncConnection], ProposalExecutor]

EXECUTORS: dict[str, ExecutorFactory] = {}
