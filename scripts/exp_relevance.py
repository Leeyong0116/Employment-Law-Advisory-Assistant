"""Experiment (2026-11-12): context selection after reranking, on gold set v1.

    docker compose run --rm -e PYTHONPATH=/app ml python scripts/exp_relevance.py

Question: why do dismissal / notice questions miss EA s.12 and s.13, and does a
different selection of the reranked candidates fix it without hurting the rest?

For every gold item it records, once:
  - the fused candidate pool at two depths (20 = current config, 40),
  - the reranker score of every candidate chunk (citation + title + content),
  - a SECTION score: the reranker on the whole section (title + every subsection),
    for every section that has a chunk in the pool, and the chunk scores of the
    sibling subsections of those sections.
Then it compares selection rules offline (same scores, no re-running):
  baseline       pool 20, top 5 by chunk score (the current pipeline)
  cutoff r       baseline, then drop chunks below r x top score
  section        pool 40 + siblings, chunk score = max(chunk, its section's score), top 5 (+ cutoff)
Reported: recall of expected chunks in the selected set, set size, precision, hit@5,
and the gate (top chunk score of the pool, as now) with 5-fold abstention rates.

Deterministic: no model chooses anything; the same question gives the same chunks.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import mean

from src.evaluation.calibration import roc_auc
from src.evaluation.retrieval_eval import kfold_abstention
from src.retrieval.fusion import rrf
from src.retrieval.pipeline import PLACEHOLDER_RULES, Retriever

OUT = Path("data/eval/runs")
EXTRA = "my boss fired me without any notice period"


def section_key(chunk: dict) -> tuple[str, str] | None:
    if not chunk.get("section") or chunk.get("chunk_type") == "definition":
        return None
    return chunk["doc_id"], chunk["section"]


def collect(r: Retriever, query: str, region: str | None) -> dict:
    s = r.settings
    allowed = s["regions"][region] if region else None
    vector = r.embedder.encode([query])[0][0]
    dense = r.store.dense_search(vector, 40, allowed, r.index_version, PLACEHOLDER_RULES)
    sparse = r.bm25.search(query, 40, allowed)
    pool20 = [c for c, _ in rrf([dense[:20], sparse[:20]])[:20]]
    pool40 = [c for c, _ in rrf([dense, sparse])[:40]]

    by_section: dict[tuple[str, str], list[str]] = defaultdict(list)
    for chunk_id, chunk in r.chunks.items():  # document order
        key = section_key(chunk)
        if key and chunk.get("parse_rule") not in PLACEHOLDER_RULES and (allowed is None or chunk["jurisdiction"] in allowed):
            by_section[key].append(chunk_id)
    sections = list(dict.fromkeys(k for c in pool40 if (k := section_key(r.chunks[c])) and k in by_section))
    siblings = [c for k in sections for c in by_section[k]]
    candidates = list(dict.fromkeys(pool40 + siblings))
    chunk_scores = dict(r.reranker.rerank(query, candidates, r.chunks))

    section_scores = {}
    for doc_id, section in sections:
        members = [r.chunks[c] for c in by_section[(doc_id, section)]]
        first = members[0]
        label = first["citation"].split(", s.")[0] + f", s. {section}" if ", s." in first["citation"] else first["citation"]
        fake = {"citation": label, "section_title": first.get("section_title"),
                "content": "\n".join(m["content"] for m in members)}
        windows = r.reranker.windows(query, fake)  # the whole section, split like any long chunk
        scores = r.reranker._load().compute_score([[query, w] for w in windows], normalize=True,
                                                  max_length=r.reranker.max_length)
        scores = [scores] if isinstance(scores, float) else scores
        section_scores[f"{doc_id}|{section}"] = float(max(scores))
    return {"pool20": pool20, "pool40": pool40, "siblings": siblings, "chunk_scores": chunk_scores,
            "section_scores": section_scores,
            "section_of": {c: "|".join(k) for c in candidates if (k := section_key(r.chunks[c]))}}


def select(data: dict, rule: str, ratio: float | None, k: int = 5) -> tuple[list[str], float]:
    cs = data["chunk_scores"]
    if rule == "baseline":
        ranked = sorted(data["pool20"], key=lambda c: (-cs[c], c))
        score = cs
    else:  # section
        ss, of = data["section_scores"], data["section_of"]
        score = {c: max(cs[c], ss.get(of.get(c, ""), 0.0)) for c in list(dict.fromkeys(data["pool40"] + data["siblings"]))}
        ranked = sorted(score, key=lambda c: (-score[c], c))
    gate = max(cs[c] for c in data["pool20"]) if data["pool20"] else 0.0  # the gate stays as today
    top = ranked[:k]
    if ratio is not None and top:
        best = score[top[0]]
        top = [c for c in top if score[c] >= ratio * best]
    return top, gate


def main() -> None:
    gold = [json.loads(line) for line in open("data/eval/gold_set.jsonl", encoding="utf-8") if line.strip()]
    r = Retriever.from_config()
    cache = OUT / f"{date.today().isoformat()}_exp_relevance_scores.json"
    if cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
    else:
        data = {}
        for item in gold + [{"id": "EXTRA", "question": EXTRA, "region": "peninsular"}]:
            if r.language_gate.check(item["question"]).passed:
                data[item["id"]] = collect(r, item["question"], item["region"])
        cache.write_text(json.dumps(data), encoding="utf-8")

    rules = [("baseline", None)] + [("baseline", x) for x in (0.1, 0.2, 0.3, 0.5)] + \
            [("section", None)] + [("section", x) for x in (0.1, 0.2, 0.3, 0.5)]
    scored = {g["id"]: g for g in gold}
    report = {}
    for rule, ratio in rules:
        name = rule + (f" cutoff {ratio}" if ratio else "")
        rows = []
        for g in gold:
            if not (g["in_scope"] and g["expected_chunk_ids"] and g["id"] in data):
                continue
            chosen, _ = select(data[g["id"]], rule, ratio)
            exp = set(g["expected_chunk_ids"])
            rows.append({"recall": len(exp & set(chosen)) / len(exp), "size": len(chosen),
                         "precision": len(exp & set(chosen)) / len(chosen) if chosen else 0.0,
                         "hit": bool(exp & set(chosen))})
        items = [(g["id"], data[g["id"]] and select(data[g["id"]], rule, ratio)[1] if g["id"] in data else -1.0, g["in_scope"])
                 for g in gold if g["scope_class"] != "external"]
        cv = kfold_abstention(items, 0.10)
        report[name] = {"n": len(rows), "recall": round(mean(x["recall"] for x in rows), 3),
                        "precision": round(mean(x["precision"] for x in rows), 3),
                        "mean_size": round(mean(x["size"] for x in rows), 2),
                        "hit": round(mean(x["hit"] for x in rows), 3),
                        "gate_auc": round(roc_auc([(s, i) for _, s, i in items]), 3),
                        "oos_declined": round(cv["out_of_scope_declined"], 3),
                        "in_scope_declined": round(cv["in_scope_declined"], 3)}
        extra, _ = select(data["EXTRA"], rule, ratio)
        report[name]["dismissal_question"] = [r.chunks[c]["citation"] for c in extra]
        for gid in ("RDT-005", "RDT-006", "RDT-007", "RDT-008"):
            chosen, _ = select(data[gid], rule, ratio)
            report[name][gid] = f"{len(set(chosen) & set(scored[gid]['expected_chunk_ids']))}/{len(chosen)} expected"
    out = OUT / f"{date.today().isoformat()}_exp_relevance_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    for name, m in report.items():
        print(f"\n{name}: " + ", ".join(f"{k} {v}" for k, v in m.items() if k not in ("dismissal_question",)))
        print("   dismissal:", m["dismissal_question"])


if __name__ == "__main__":
    main()
