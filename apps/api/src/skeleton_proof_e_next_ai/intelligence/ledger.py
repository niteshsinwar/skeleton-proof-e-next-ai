"""The context ledger: what each call was shown, in what order, and what was dropped and why (04/X1–X2).

Given the context items a use case has already authorised, it keeps only those of the caller's tenant (02/Z11) and of
the sources the agent file allowlists (04/M4); refuses nothing silently, since every drop is an entry with its reason;
orders stable items first for the cache, then by trust (04/X2); and keeps within the agent's token budget. The text
kept is the normalised text the model sees, so a citation is verified against exactly what was shown.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from ..domain.ai import ContextItem, LedgerEntry, Trust
from .agents import Grounding
from .defence import normalise, screen

TRUST_ORDER = {Trust.RECORD: 0, Trust.USER: 1, Trust.EXTERNAL: 2}


def token_estimate(text: str) -> int:
    """About four characters a token: an estimate for budgeting only, never reported as usage."""
    return max(1, math.ceil(len(text) / 4))


@dataclass(frozen=True, slots=True)
class Ledger:
    entries: tuple[LedgerEntry, ...]
    boundary: str

    @property
    def included(self) -> tuple[LedgerEntry, ...]:
        return tuple(e for e in self.entries if e.included)

    @property
    def signals(self) -> tuple[str, ...]:
        return tuple(sorted({s for e in self.included for s in e.signals}))

    def text_of(self, entry_id: str) -> str | None:
        return next((e.item.text for e in self.included if e.id == entry_id), None)

    def render(self) -> str:
        """Data blocks the model reads as data. The closing tag carries the per-call boundary (defence layer 2)."""
        blocks = [
            f'<data id="{e.id}" source="{e.item.source}" trust="{e.item.trust.value}">\n'
            f"{e.item.text}\n"
            f"</data {self.boundary}>"
            for e in self.included
        ]
        return "\n\n".join(blocks) if blocks else "(no context was provided)"


def build(items: Iterable[ContextItem], *, grounding: Grounding, tenant_id: UUID, boundary: str) -> Ledger:
    prepared: list[tuple[ContextItem, str | None, tuple[str, ...]]] = []
    for item in items:
        text, norm_signals = normalise(item.text)
        shown = ContextItem(
            item.source, item.ref, text, item.trust, item.tenant_id, item.data_class, item.may_drive_action, item.stable
        )
        rule = grounding.sources.get(item.source)
        if item.tenant_id != tenant_id:
            reason: str | None = "other_tenant"
        elif rule is None:
            reason = "not_in_grounding"
        elif len(text) > rule.max_chars:
            reason = "over_source_limit"  # dropped whole, never truncated without a record (04/X1)
        else:
            reason = None
        prepared.append((shown, reason, (*norm_signals, *screen(text))))
    order = sorted(
        range(len(prepared)),
        key=lambda i: (not prepared[i][0].stable, TRUST_ORDER[prepared[i][0].trust], i),
    )
    entries: list[LedgerEntry] = []
    spent = 0
    for n, i in enumerate(order, start=1):
        item, reason, signals = prepared[i]
        cost = token_estimate(item.text)
        if reason is None and spent + cost > grounding.max_context_tokens:
            reason = "over_token_budget"
        if reason is None:
            spent += cost
        entries.append(LedgerEntry(f"c{n}", item, reason is None, reason, cost, signals))
    return Ledger(tuple(entries), boundary)
