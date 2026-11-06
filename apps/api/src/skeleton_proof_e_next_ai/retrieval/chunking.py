"""Structure-aware chunking (04/X4): split on headings and paragraphs, never mid-sentence by a character count alone.

Deterministic: the same text always gives the same chunks, so a re-index is reproducible and a citation stays valid.
A paragraph longer than the limit is split at sentence ends; nothing is dropped and nothing overlaps.
"""

from __future__ import annotations

import re

from ..domain.retrieval import Chunk

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def chunk(text: str, *, max_chars: int = 1200) -> list[Chunk]:
    path: list[str] = []
    out: list[Chunk] = []
    paragraph: list[str] = []

    def flush() -> None:
        body = " ".join(" ".join(paragraph).split())
        paragraph.clear()
        if not body:
            return
        for piece in _split(body, max_chars):
            out.append(Chunk(position=len(out) + 1, heading=" > ".join(path), text=piece))

    for line in text.splitlines():
        heading = HEADING.match(line)
        if heading:
            flush()
            level = len(heading.group(1))
            del path[level - 1 :]
            path.append(heading.group(2))
        elif not line.strip():
            flush()
        else:
            paragraph.append(line.strip())
    flush()
    return out


def _split(body: str, max_chars: int) -> list[str]:
    if len(body) <= max_chars:
        return [body]
    pieces: list[str] = []
    current = ""
    for sentence in SENTENCE_END.split(body):
        if current and len(current) + 1 + len(sentence) > max_chars:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
        while len(current) > max_chars:  # one sentence longer than the limit: cut it, still dropping nothing
            pieces.append(current[:max_chars])
            current = current[max_chars:]
    if current:
        pieces.append(current)
    return pieces
