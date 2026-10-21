"""Gate rules for the offline query-rewrite experiment (plan 2026-10-21).

Each question has two reranker gate scores: on the user's original wording
(orig) and on the LLM rewrite (rew). A rule decides from these whether the
question is answered, and which retrieval supplies the chunks. Rules:

    baseline   orig >= t                                  (today's system)
    rewrite    rew >= t
    max        max(orig, rew) >= t                        chunks from the higher
    or_strict  orig >= t_o, else rew >= t_r (t_r >= t_o)
    band       orig >= t, else orig >= low and rew >= t   (near-miss band)

Every rule is tuned the same way, the author's constraint: on the training
folds, decline at least 70% of out-of-scope questions, and among the
parameters that do, answer as many in-scope questions as possible. Rates
are pooled over held-out folds. A score equal to a threshold passes, as in
src/retrieval/pipeline.py.

The gate decides whether there is something to answer from; it does not
check legal correctness (CLAUDE.md, core contribution 2).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

STOPPED = -1.0          # gate score of a question stopped by the language gate
MIN_OOS_DECLINED = 0.70
RULES = ("baseline", "rewrite", "max", "or_strict", "band")


@dataclass(frozen=True)
class Scored:
    id: str
    in_scope: bool
    orig: float
    rew: float
    fold_of: str        # its own id; the English parent's id for a Malay variant


def select_oos_threshold(oos_scores: list[float], min_declined: float = MIN_OOS_DECLINED) -> float:
    """Lowest threshold that declines at least min_declined of the scores (declined: score < threshold)."""
    if not oos_scores:
        raise ValueError("need out-of-scope scores to tune")
    k = math.ceil(min_declined * len(oos_scores) - 1e-9)
    return math.nextafter(sorted(oos_scores)[k - 1], math.inf)


def passes(rule: str, item: Scored, params: dict) -> tuple[bool, str]:
    """(answered?, source of the chunks: "orig" or "rew")."""
    if rule == "baseline":
        return item.orig >= params["t"], "orig"
    if rule == "rewrite":
        return item.rew >= params["t"], "rew"
    if rule == "max":
        source = "orig" if item.orig >= item.rew else "rew"
        return max(item.orig, item.rew) >= params["t"], source
    if rule == "or_strict":
        if item.orig >= params["t_o"]:
            return True, "orig"
        return item.rew >= params["t_r"], "rew"
    if rule == "band":
        if item.orig >= params["t"]:
            return True, "orig"
        return params["low"] <= item.orig and item.rew >= params["t"], "rew"
    raise ValueError(f"unknown rule {rule!r}")


def _feasible(rule: str, params: dict, train: list[Scored]) -> bool:
    oos = [i for i in train if not i.in_scope]
    declined = sum(not passes(rule, i, params)[0] for i in oos)
    return declined >= math.ceil(MIN_OOS_DECLINED * len(oos) - 1e-9)


def tune(rule: str, train: list[Scored]) -> dict:
    """Parameters for a rule, chosen on training items only."""
    oos = [i for i in train if not i.in_scope]
    if rule in ("baseline", "rewrite", "max"):
        score = {"baseline": lambda i: i.orig, "rewrite": lambda i: i.rew, "max": lambda i: max(i.orig, i.rew)}[rule]
        return {"t": select_oos_threshold([score(i) for i in oos])}
    t = select_oos_threshold([i.orig for i in oos])
    if rule == "or_strict":
        candidates = sorted({t, math.inf} | {math.nextafter(i.rew, math.inf) for i in oos if i.rew >= t})
        return {"t_o": t, "t_r": next(c for c in candidates if _feasible(rule, {"t_o": t, "t_r": c}, train))}
    if rule == "band":
        # Lowest band edge first: the widest band that still keeps the constraint.
        candidates = sorted({i.orig for i in train if i.orig < t}) + [t]
        return {"t": t, "low": next(c for c in candidates if _feasible(rule, {"t": t, "low": c}, train))}
    raise ValueError(f"unknown rule {rule!r}")


def _folds(items: list[Scored], k: int) -> dict[str, int]:
    """Same assignment as kfold_abstention in src/evaluation/retrieval_eval.py."""
    gold = [i for i in items if i.fold_of == i.id]
    folds: dict[str, int] = {}
    for in_scope in (True, False):
        group = sorted(i.id for i in gold if i.in_scope == in_scope)
        folds.update({item_id: n % k for n, item_id in enumerate(group)})
    return folds


def kfold(rule: str, items: list[Scored], k: int = 5) -> dict:
    """Tune on k-1 folds, decide the held-out fold; rates pooled over gold items only."""
    folds = _folds(items, k)
    gold = [i for i in items if i.fold_of == i.id]
    decisions, fold_params = {}, []
    for fold in range(k):
        params = tune(rule, [i for i in gold if folds[i.id] != fold])
        fold_params.append(params)
        for i in items:
            if folds[i.fold_of] == fold:
                passed, source = passes(rule, i, params)
                decisions[i.id] = {"passed": passed, "source": source, "fold": fold}

    def declined(in_scope: bool) -> float:
        group = [i for i in gold if i.in_scope == in_scope]
        return sum(not decisions[i.id]["passed"] for i in group) / len(group) if group else 0.0

    return {"out_of_scope_declined": declined(False), "in_scope_declined": declined(True),
            "fold_params": fold_params, "decisions": decisions}
