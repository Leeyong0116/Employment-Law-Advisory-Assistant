"""Experiment (2026-11-12): same candidate pools, different cross-encoder.

    docker compose run --rm -e PYTHONPATH=/app ml python scripts/exp_reranker_model.py <scores.json> [model ...]

Reads the pools saved by scripts/exp_relevance.py (pool of 20 = the current pipeline) and
reranks them with each model, taking the top 5. Retrieval before reranking is identical,
so differences come from the reranker alone. Gate figures use each model's top score with
the same 5-fold rule as src/evaluation/retrieval_eval.py.
"""

from __future__ import annotations

import json
import sys
from statistics import mean

from src.evaluation.calibration import roc_auc
from src.evaluation.retrieval_eval import kfold_abstention
from src.retrieval.pipeline import Retriever
from src.retrieval.rerank import Reranker


def main() -> None:
    scores_path, models = sys.argv[1], sys.argv[2:] or ["BAAI/bge-reranker-large", "BAAI/bge-reranker-v2-m3"]
    data = json.load(open(scores_path, encoding="utf-8"))
    gold = [json.loads(line) for line in open("data/eval/gold_set.jsonl", encoding="utf-8") if line.strip()]
    chunks = Retriever.__new__(Retriever)  # only the chunk table is needed
    chunks = {c["chunk_id"]: c for c in map(json.loads, open("data/processed/chunks.jsonl", encoding="utf-8"))}
    queries = {g["id"]: g["question"] for g in gold} | {"EXTRA": "my boss fired me without any notice period"}

    for model in models:
        reranker = Reranker(model)
        top = {i: reranker.rerank(queries[i], d["pool20"], chunks)[:5] for i, d in data.items()}
        rows = []
        for g in gold:
            if g["in_scope"] and g["expected_chunk_ids"] and g["id"] in top:
                ids, exp = [c for c, _ in top[g["id"]]], set(g["expected_chunk_ids"])
                rows.append((bool(exp & set(ids)), len(exp & set(ids)) / len(exp),
                             next((1 / n for n, c in enumerate(ids, 1) if c in exp), 0.0)))
        gate = [(g["id"], top[g["id"]][0][1] if g["id"] in top and top[g["id"]] else -1.0, g["in_scope"])
                for g in gold if g["scope_class"] != "external"]
        cv = kfold_abstention(gate, 0.10)
        print(f"\n== {model}")
        print(f"hit@5 {mean(r[0] for r in rows):.3f}  mrr {mean(r[2] for r in rows):.3f}  recall_top5 {mean(r[1] for r in rows):.3f}  "
              f"gate auc {roc_auc([(s, i) for _, s, i in gate]):.3f}  5-fold oos declined {cv['out_of_scope_declined']:.2f}  "
              f"in-scope declined {cv['in_scope_declined']:.2f}")
        print("dismissal:", [(chunks[c]["citation"].split(", ")[-1], round(s, 3)) for c, s in top["EXTRA"]])
        for gid in ("RDT-005", "RDT-006", "RDT-007", "RDT-008"):
            exp = set(next(g for g in gold if g["id"] == gid)["expected_chunk_ids"])
            print(f"{gid}: {sum(c in exp for c, _ in top[gid])}/5 expected  {[c for c, _ in top[gid]]}")
        reranker.close()


if __name__ == "__main__":
    main()
