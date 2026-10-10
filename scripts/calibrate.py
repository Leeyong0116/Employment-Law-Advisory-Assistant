"""Measure each mode's gate score on labelled questions and pick thresholds.

    docker compose run --rm ml python scripts/calibrate.py data/eval/dev_questions.jsonl

Question lines: {"id", "question", "region", "in_scope": true/false}, the
same format the gold set will use. Retrieval runs with the gate off, so
every question gets a gate score; questions the language gate stops have
none and are listed separately.

For each mode it prints the threshold-free separation (ROC AUC), the
threshold chosen by the fixed rule (highest threshold with in-scope
questions wrongly declined within --budget), and the rates at that
threshold. Scores are saved, so thresholds and curves can be recomputed
without rerunning retrieval.

Thresholds from the developer-written dev list are provisional and are
never reported as results; the gold set replaces them (plan 2026-10-10,
decision 3).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.evaluation.calibration import rates, roc_auc, select_threshold  # noqa: E402
from src.retrieval.pipeline import MODES, Retriever  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate abstention thresholds.")
    parser.add_argument("questions", type=Path)
    parser.add_argument("--modes", nargs="+", choices=MODES, default=list(MODES))
    parser.add_argument("--budget", type=float, default=0.10, help="max share of in-scope questions declined")
    parser.add_argument("--out", type=Path, help="where to save scores (default: next to the questions)")
    args = parser.parse_args()

    questions = [json.loads(line) for line in args.questions.open(encoding="utf-8") if line.strip()]
    out = args.out or args.questions.with_name(args.questions.stem + "_gate_scores.json")
    retriever = Retriever.from_config()

    saved = {"questions": str(args.questions), "budget": args.budget, "modes": {}}
    for mode in args.modes:
        rows = []
        for q in questions:
            result = retriever.retrieve(q["question"], q.get("region"), mode, gate=False)
            top = next((c for c in result.chunks if c.rank == 1), None)
            rows.append({"id": q["id"], "in_scope": q["in_scope"], "gate_score": result.gate_score,
                         "abstain_reason": result.abstain_reason, "top": top.citation if top else None})
        items = [(r["gate_score"], r["in_scope"]) for r in rows if r["gate_score"] is not None]
        threshold = select_threshold(items, args.budget)
        summary = {"auc": roc_auc(items), "threshold": threshold, **rates(items, threshold),
                   "stopped_before_scoring": [r["id"] for r in rows if r["gate_score"] is None]}
        saved["modes"][mode] = {"summary": summary, "rows": rows}

        print(f"\n== {mode} ==  AUC {summary['auc']:.3f}  threshold {threshold:.4f}  "
              f"out-of-scope declined {summary['out_of_scope_declined']:.0%}  "
              f"in-scope declined {summary['in_scope_declined']:.0%}")
        if summary["stopped_before_scoring"]:
            print(f"   stopped before scoring: {summary['stopped_before_scoring']}")
        for r in sorted(rows, key=lambda r: (r["gate_score"] is None, -(r["gate_score"] or 0))):
            score = "  -   " if r["gate_score"] is None else f"{r['gate_score']:.4f}"
            label = "IN " if r["in_scope"] else "OUT"
            mark = "" if r["gate_score"] is None or (r["gate_score"] >= threshold) == r["in_scope"] else "  <- wrong side"
            print(f"   {score}  {label}  {r['id']:28s} {r['top'] or r['abstain_reason']}{mark}")

    out.write_text(json.dumps(saved, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nscores saved to {out}")


if __name__ == "__main__":
    main()
