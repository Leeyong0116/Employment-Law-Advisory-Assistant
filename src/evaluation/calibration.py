"""Abstention threshold arithmetic, kept separate from retrieval so it is testable.

Input is a list of (gate score, in scope?) pairs, one per labelled question,
produced with the gate switched off. A question is declined when its score
is below the threshold; a score equal to the threshold is answered (the same
rule as src/retrieval/pipeline.py).

The selection rule is fixed before any run and is the same for every mode
(plan 2026-10-10, Section 7a): the highest threshold that keeps the share of
in-scope questions wrongly declined within a budget. Abstention is then
compared across modes at equal cost to in-scope users.
"""

from __future__ import annotations

Item = tuple[float, bool]


def rates(items: list[Item], threshold: float) -> dict[str, float]:
    """Share of out-of-scope questions declined and of in-scope questions declined."""
    inside = [score for score, in_scope in items if in_scope]
    outside = [score for score, in_scope in items if not in_scope]
    share = lambda scores: sum(s < threshold for s in scores) / len(scores) if scores else 0.0  # noqa: E731
    return {"out_of_scope_declined": share(outside), "in_scope_declined": share(inside)}


def roc_auc(items: list[Item]) -> float:
    """Probability that an in-scope question outscores an out-of-scope one (ties count half).

    Threshold-free: how well the gate score separates the two groups at all.
    """
    inside = [score for score, in_scope in items if in_scope]
    outside = [score for score, in_scope in items if not in_scope]
    if not inside or not outside:
        raise ValueError("need both in-scope and out-of-scope items")
    wins = sum((a > b) + 0.5 * (a == b) for a in inside for b in outside)
    return wins / (len(inside) * len(outside))


def select_threshold(items: list[Item], max_in_scope_declined: float) -> float:
    """Highest threshold whose in-scope decline rate stays within the budget.

    Only in-scope scores are candidates: between two of them the in-scope
    rate does not change, so the highest allowed value is always one of them.
    """
    inside = sorted(score for score, in_scope in items if in_scope)
    if not inside:
        raise ValueError("need in-scope items to calibrate")
    allowed = int(max_in_scope_declined * len(inside) + 1e-9)  # questions we may decline
    return inside[min(allowed, len(inside) - 1)]
