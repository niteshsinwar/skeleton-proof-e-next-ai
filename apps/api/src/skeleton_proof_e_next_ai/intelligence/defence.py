"""Injection defence: structural, layered, and never dependent on the model obeying (05/SG5, OWASP LLM01).

Prompt injection is assumed to succeed sometimes, so the controls don't try to make the model immune:

1. **Bounds and normalisation** (here): Unicode NFKC, and control, invisible and bidirectional-override characters
   removed, each removal recorded as a signal.
2. **Segregation** (ledger.py): every item sits in its own data block whose closing tag carries a random per-call
   boundary, so planted text can't close the block it is in; the system prompt says data blocks are never
   instructions.
3. **Screening** (here): deterministic patterns that look like instructions. A signal only ever **raises** risk
   (flag for review, or block when the agent file says so); it never lowers it (04/P4).
4. **Authority removal** (registry, tools): untrusted text can't drive an action; writes are proposals.
5. **Output checks** (validation.py): schema, verified citations, links only to allowlisted hosts; screens render
   model text as text, never as markup.
"""

from __future__ import annotations

import re
import unicodedata

INVISIBLE = {chr(c) for c in (0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x00AD)}  # zero-width, joiners, BOM, soft hyphen
BIDI = {chr(c) for c in (*range(0x202A, 0x202F), *range(0x2066, 0x206A))}

PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "instruction_override",
        re.compile(
            r"\b(ignore|disregard|forget|override)\b.{0,40}\b(instructions?|rules|prompt|above|previous|prior)\b",
            re.I | re.S,
        ),
    ),
    ("role_claim", re.compile(r"\b(you are now|act as|pretend to be|new instructions?)\b", re.I)),
    ("prompt_reference", re.compile(r"\b(system|developer)\s+(prompt|message|instructions?)\b", re.I)),
    ("markup_tag", re.compile(r"</?\s*(system|assistant|user|data|instructions?)\b", re.I)),
    ("encoded_payload", re.compile(r"[A-Za-z0-9+/]{120,}={0,2}")),
    ("link", re.compile(r"\bhttps?://", re.I)),
)


def normalise(text: str) -> tuple[str, tuple[str, ...]]:
    """What the model is shown. Removals are recorded, never silent (04/X1)."""
    out = unicodedata.normalize("NFKC", text)
    signals: list[str] = []
    if any(ch in INVISIBLE for ch in out):
        signals.append("invisible_characters")
        out = "".join(ch for ch in out if ch not in INVISIBLE)
    if any(ch in BIDI for ch in out):
        signals.append("bidi_override")
        out = "".join(ch for ch in out if ch not in BIDI)
    if any(unicodedata.category(ch) == "Cc" and ch not in "\n\t" for ch in out):
        signals.append("control_characters")
        out = "".join(ch for ch in out if unicodedata.category(ch) != "Cc" or ch in "\n\t")
    return out, tuple(signals)


def screen(text: str) -> tuple[str, ...]:
    """Deterministic signals: evidence for a reviewer and an input to policy, never a verdict on their own."""
    return tuple(name for name, pattern in PATTERNS if pattern.search(text))
