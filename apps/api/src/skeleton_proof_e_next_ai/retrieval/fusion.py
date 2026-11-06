"""Reciprocal rank fusion (04/X4): combine ranked lanes by position, not by their incomparable raw scores."""

from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence

RRF_K = 60  # the usual constant: damps the head so one lane's top result can't dominate alone


def rrf[K: Hashable](lanes: Mapping[str, Sequence[K]], *, k: int = RRF_K) -> list[tuple[K, float, tuple[str, ...]]]:
    """Fuse ranked lists of ids. Ties break by the earliest lane and rank that found an item: a stable order."""
    scores: dict[K, float] = {}
    found: dict[K, list[str]] = {}
    first: dict[K, tuple[int, int]] = {}
    for lane_no, (lane, ranked) in enumerate(lanes.items()):
        for rank, item in enumerate(ranked, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
            found.setdefault(item, []).append(lane)
            first.setdefault(item, (lane_no, rank))
    ordered = sorted(scores, key=lambda i: (-scores[i], first[i]))
    return [(i, scores[i], tuple(found[i])) for i in ordered]
