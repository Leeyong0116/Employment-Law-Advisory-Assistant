"""Combine ranked lists from different retrievers.

Dense similarity (0 to 1) and BM25 scores (unbounded) are on different
scales, so they cannot be added. Reciprocal rank fusion uses ranks only:

    score(chunk) = sum over lists of 1 / (c + rank in that list)

A chunk ranked high in both lists beats one ranked high in only one. c = 60
is the value from the original paper (Cormack, Clarke and Buettcher, 2009)
and damps the advantage of the very top ranks.

Ties are broken by chunk_id, so fusion is deterministic.
"""

from __future__ import annotations

from collections import defaultdict

RRF_C = 60


def rrf(ranked_lists: list[list[tuple[str, float]]], c: int = RRF_C) -> list[tuple[str, float]]:
    """Fuse lists of (chunk_id, score), best first, into one fused list."""
    fused: dict[str, float] = defaultdict(float)
    for ranked in ranked_lists:
        for rank, (chunk_id, _score) in enumerate(ranked, start=1):
            fused[chunk_id] += 1.0 / (c + rank)
    return sorted(fused.items(), key=lambda item: (-item[1], item[0]))
