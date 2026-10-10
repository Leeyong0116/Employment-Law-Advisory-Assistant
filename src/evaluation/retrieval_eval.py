"""Retrieval evaluation on the gold set, for all three retrieval modes.

    python -m src.evaluation.retrieval_eval [--gold data/eval/gold_set.jsonl] [--budget 0.10]

What it measures (no generation, no judge LLM, so it is deterministic):

- Retrieval, on in-scope items with expected chunks, gate off:
    hit@1, hit@5 and MRR on the ranked top 5;
    recall on the top 5 alone and on the final result (top 5 + expansion),
    so the effect of amendment links and definition co-retrieval is visible;
    RAGAS ID-based context precision and recall on the final result
    (set overlap between retrieved and expected chunk ids).
- Abstention, in-scope versus out-of-scope (external items reported apart):
    ROC AUC of each mode's gate score (threshold-free),
    rates at the threshold chosen on all items (in-sample, optimistic),
    and 5-fold cross-validated rates (threshold chosen on four folds,
    applied to the fifth), the figure to report (plan 2026-10-10, 7a).

This checks that the right provisions are retrieved. It does not check that
a provision legally supports an answer (CLAUDE.md, core contribution 2).
Answer metrics (faithfulness, answer relevancy) need M4 generation.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import warnings
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import mean

from src.evaluation.calibration import rates, roc_auc, select_threshold

STOPPED = -1.0  # gate score for a question stopped before scoring (language gate)


def hit_at_k(ranked: list[str], expected: list[str], k: int) -> bool:
    return any(chunk_id in expected for chunk_id in ranked[:k])


def recall(found: list[str], expected: list[str]) -> float:
    if not expected:
        raise ValueError("recall needs at least one expected chunk")
    return len(set(found) & set(expected)) / len(set(expected))


def reciprocal_rank(ranked: list[str], expected: list[str]) -> float:
    for rank, chunk_id in enumerate(ranked, start=1):
        if chunk_id in expected:
            return 1.0 / rank
    return 0.0


def kfold_abstention(items: list[tuple[str, float, bool]], budget: float, k: int = 5) -> dict:
    """Cross-validated decline rates. items: (id, gate score, in scope?).

    Folds are stratified and deterministic: in-scope and out-of-scope items
    are each sorted by id and dealt round-robin into k folds. For each fold,
    the threshold is chosen on the other folds with select_threshold and
    applied to this fold; counts are pooled over the folds.
    """
    folds: dict[str, int] = {}
    for in_scope in (True, False):
        group = sorted(i for i, _, s in items if s == in_scope)
        folds.update({item_id: n % k for n, item_id in enumerate(group)})
    declined = {True: 0, False: 0}
    totals = {True: 0, False: 0}
    thresholds, tested = [], []
    for fold in range(k):
        train = [(score, s) for i, score, s in items if folds[i] != fold]
        test = [(i, score, s) for i, score, s in items if folds[i] == fold]
        if not test:
            continue
        threshold = select_threshold(train, budget)
        thresholds.append(threshold)
        for item_id, score, in_scope in test:
            tested.append(item_id)
            totals[in_scope] += 1
            declined[in_scope] += score < threshold
    return {
        "out_of_scope_declined": declined[False] / totals[False] if totals[False] else 0.0,
        "in_scope_declined": declined[True] / totals[True] if totals[True] else 0.0,
        "fold_thresholds": thresholds,
        "tested_ids": tested,
    }


def ragas_id_scores(retrieved: list[str], expected: list[str]) -> tuple[float, float]:
    """RAGAS IDBasedContextPrecision and IDBasedContextRecall for one item."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)  # import path moves in ragas 1.0
        from ragas.dataset_schema import SingleTurnSample
        from ragas.metrics import IDBasedContextPrecision, IDBasedContextRecall
    sample = SingleTurnSample(retrieved_context_ids=retrieved, reference_context_ids=expected)

    async def both():
        return (await IDBasedContextPrecision().single_turn_ascore(sample),
                await IDBasedContextRecall().single_turn_ascore(sample))

    precision, rec = asyncio.run(both())
    return float(precision), float(rec)


def run(retriever, gold: list[dict], modes) -> list[dict]:
    """One record per (mode, item), gate off."""
    records = []
    for mode in modes:
        for item in gold:
            result = retriever.retrieve(item["question"], item["region"], mode, gate=False)
            records.append({
                "mode": mode, "id": item["id"],
                "gate_score": result.gate_score, "abstain_reason": result.abstain_reason,
                "multiple_jurisdictions": result.multiple_jurisdictions,
                "ranked": [c.chunk_id for c in result.chunks if c.added_because == "retrieved"],
                "final": [c.chunk_id for c in result.chunks],
            })
    return records


def region_group(item: dict) -> str:
    if item["region"]:
        return item["region"]
    return "all (IRA)" if item["id"].startswith("JPPM") else "no region"


def retrieval_metrics(records: list[dict], gold: dict[str, dict]) -> dict:
    rows = [r for r in records if gold[r["id"]]["in_scope"] and gold[r["id"]]["expected_chunk_ids"]]

    def summarise(subset):
        per = []
        for r in subset:
            exp = gold[r["id"]]["expected_chunk_ids"]
            precision, rec = ragas_id_scores(r["final"], exp)
            per.append({
                "hit@1": hit_at_k(r["ranked"], exp, 1), "hit@5": hit_at_k(r["ranked"], exp, 5),
                "mrr": reciprocal_rank(r["ranked"], exp),
                "recall_top5": recall(r["ranked"], exp), "recall_final": recall(r["final"], exp),
                "ragas_id_precision": precision, "ragas_id_recall": rec,
            })
        return {"n": len(per), **{k: round(mean(p[k] for p in per), 3) for k in per[0]}} if per else {"n": 0}

    out = {"overall": summarise(rows)}
    for key, fn in (("by_region", region_group), ("by_difficulty", lambda g: g["difficulty"]),
                    ("by_check", lambda g: g["check"]), ("by_topic", lambda g: g["topic"])):
        groups = defaultdict(list)
        for r in rows:
            groups[fn(gold[r["id"]])].append(r)
        out[key] = {name: summarise(g) for name, g in sorted(groups.items())}
    out["misses_at_5"] = [r["id"] for r in rows if not hit_at_k(r["ranked"], gold[r["id"]]["expected_chunk_ids"], 5)]
    return out


def abstention_metrics(records: list[dict], gold: dict[str, dict], budget: float) -> dict:
    scored = [(r["id"], STOPPED if r["gate_score"] is None else r["gate_score"], gold[r["id"]]["in_scope"])
              for r in records if gold[r["id"]]["scope_class"] != "external"]
    pairs = [(score, in_scope) for _, score, in_scope in scored]
    threshold = select_threshold(pairs, budget)
    cv = kfold_abstention(scored, budget)
    cv.pop("tested_ids")
    return {
        "auc": round(roc_auc(pairs), 3),
        "in_sample": {"threshold": round(threshold, 4), **{k: round(v, 3) for k, v in rates(pairs, threshold).items()}},
        "cross_validated_5fold": {k: (round(v, 3) if isinstance(v, float) else [round(t, 4) for t in v]) for k, v in cv.items()},
        "external": {r["id"]: r["gate_score"] for r in records if gold[r["id"]]["scope_class"] == "external"},
        "stopped_by_language": [r["id"] for r in records if r["abstain_reason"] == "language"],
    }


def main() -> None:
    from src.retrieval.pipeline import MODES, Retriever

    parser = argparse.ArgumentParser(description="Retrieval evaluation on the gold set.")
    parser.add_argument("--gold", type=Path, default=Path("data/eval/gold_set.jsonl"))
    parser.add_argument("--budget", type=float, default=0.10, help="max share of in-scope questions declined")
    parser.add_argument("--out-dir", type=Path, default=Path("data/eval/runs"))
    args = parser.parse_args()

    gold_items = [json.loads(line) for line in args.gold.open(encoding="utf-8") if line.strip()]
    gold = {g["id"]: g for g in gold_items}
    retriever = Retriever.from_config()
    records = run(retriever, gold_items, MODES)

    report = {"gold": str(args.gold), "items": len(gold_items), "index_version": retriever.index_version,
              "budget": args.budget, "modes": {}}
    for mode in MODES:
        mode_records = [r for r in records if r["mode"] == mode]
        report["modes"][mode] = {"retrieval": retrieval_metrics(mode_records, gold),
                                 "abstention": abstention_metrics(mode_records, gold, args.budget)}

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{date.today().isoformat()}_retrieval"
    with (args.out_dir / f"{stem}_records.jsonl").open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (args.out_dir / f"{stem}_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    keys = ("hit@1", "hit@5", "mrr", "recall_top5", "recall_final", "ragas_id_precision", "ragas_id_recall")
    print(f"\nRetrieval, {report['modes'][MODES[0]]['retrieval']['overall']['n']} in-scope items, gate off")
    print(f"{'mode':15}" + "".join(f"{k:>20}" for k in keys))
    for mode in MODES:
        o = report["modes"][mode]["retrieval"]["overall"]
        print(f"{mode:15}" + "".join(f"{o[k]:>20.3f}" for k in keys))
    print(f"\nAbstention (in-scope vs out-of-scope; budget {args.budget:.0%} in-scope declined)")
    print(f"{'mode':15}{'AUC':>8}{'thr (all)':>12}{'out decl.':>11}{'in decl.':>10}{'CV out decl.':>14}{'CV in decl.':>13}")
    for mode in MODES:
        a = report["modes"][mode]["abstention"]
        print(f"{mode:15}{a['auc']:>8.3f}{a['in_sample']['threshold']:>12.4f}"
              f"{a['in_sample']['out_of_scope_declined']:>11.0%}{a['in_sample']['in_scope_declined']:>10.0%}"
              f"{a['cross_validated_5fold']['out_of_scope_declined']:>14.0%}{a['cross_validated_5fold']['in_scope_declined']:>13.0%}")
    print(f"\nreport: {args.out_dir / (stem + '_report.json')}")


if __name__ == "__main__":
    main()
