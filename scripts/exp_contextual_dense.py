"""Experiment (2026-11-12): embed citation + section title + content for dense search.

    docker compose run --rm -e PYTHONPATH=/app ml python scripts/exp_contextual_dense.py

CP1 locks "only `content` is embedded". A subsection such as EA s.12(2) ("The length of
such notice ...") then never contains the words of its own topic, which sit in the
section title ("Notice of termination of contract"). This re-embeds every chunk in memory
with the same header the reranker and BM25 already read (src/retrieval/rerank.passage),
runs the rest of the pipeline unchanged (BM25, RRF, reranker, top 5), and compares with
the indexed content-only vectors on gold set v1. The database is not changed.
"""

from __future__ import annotations

import json
from statistics import mean

import numpy as np

from src.evaluation.calibration import roc_auc
from src.evaluation.retrieval_eval import kfold_abstention
from src.retrieval.fusion import rrf
from src.retrieval.pipeline import PLACEHOLDER_RULES, Retriever
from src.retrieval.rerank import passage

EXTRA = "my boss fired me without any notice period"


def main() -> None:
    gold = [json.loads(line) for line in open("data/eval/gold_set.jsonl", encoding="utf-8") if line.strip()]
    r = Retriever.from_config()
    s = r.settings
    ids = [c for c, chunk in r.chunks.items() if chunk.get("parse_rule") not in PLACEHOLDER_RULES]
    dense_vectors, _ = r.embedder.encode([passage(r.chunks[c]) for c in ids])
    matrix = np.asarray(dense_vectors, dtype=np.float32)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    jurisdiction = np.array([r.chunks[c]["jurisdiction"] for c in ids])

    def contextual_dense(vector, allowed, k):
        v = np.asarray(vector, dtype=np.float32)
        sims = matrix @ (v / np.linalg.norm(v))
        if allowed:
            sims = np.where(np.isin(jurisdiction, allowed), sims, -np.inf)
        order = np.argsort(-sims)[:k]
        return [(ids[i], float(sims[i])) for i in order]

    def retrieve(query, region, contextual):
        allowed = s["regions"][region] if region else None
        vector = r.embedder.encode([query])[0][0]
        dense = (contextual_dense(vector, allowed, s["top_k_dense"]) if contextual
                 else r.store.dense_search(vector, s["top_k_dense"], allowed, r.index_version, PLACEHOLDER_RULES))
        pool = rrf([dense, r.bm25.search(query, s["top_k_sparse"], allowed)])[:s["rerank_pool"]]
        top = r.reranker.rerank(query, [c for c, _ in pool], r.chunks)[:s["top_k_final"]]
        return [c for c, _ in top], (top[0][1] if top else -1.0)

    report = {}
    for contextual in (False, True):
        name = "contextual (citation + title + content)" if contextual else "content only (current)"
        rows, gate = [], []
        for g in gold:
            if not r.language_gate.check(g["question"]).passed:
                gate.append((g["id"], -1.0, g["in_scope"])) if g["scope_class"] != "external" else None
                continue
            top, score = retrieve(g["question"], g["region"], contextual)
            if g["scope_class"] != "external":
                gate.append((g["id"], score, g["in_scope"]))
            if g["in_scope"] and g["expected_chunk_ids"]:
                exp = set(g["expected_chunk_ids"])
                rows.append({"id": g["id"], "hit": bool(exp & set(top)), "recall": len(exp & set(top)) / len(exp),
                             "rr": next((1 / n for n, c in enumerate(top, 1) if c in exp), 0.0)})
        cv = kfold_abstention(gate, 0.10)
        dismissal, _ = retrieve(EXTRA, "peninsular", contextual)
        report[name] = {
            "hit@5": round(mean(x["hit"] for x in rows), 3), "mrr": round(mean(x["rr"] for x in rows), 3),
            "recall_top5": round(mean(x["recall"] for x in rows), 3), "gate_auc": round(roc_auc([(sc, i) for _, sc, i in gate]), 3),
            "oos_declined_5fold": round(cv["out_of_scope_declined"], 3), "in_scope_declined_5fold": round(cv["in_scope_declined"], 3),
            "misses": [x["id"] for x in rows if not x["hit"]],
            "dismissal_question": [r.chunks[c]["citation"] for c in dismissal],
            **{gid: [c for c in retrieve(next(g for g in gold if g["id"] == gid)["question"], None, contextual)[0]]
               for gid in ("RDT-005", "RDT-006", "RDT-007", "RDT-008")},
        }
    print(json.dumps(report, indent=1, ensure_ascii=False))
    with open("data/eval/runs/2026-11-12_exp_contextual_dense_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
