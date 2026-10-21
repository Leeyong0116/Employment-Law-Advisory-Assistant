"""Offline query-rewrite experiment (plan docs/plans/2026-10-21-query-rewrite-experiment.md).

    docker compose run --rm ml python scripts/exp_query_rewrite.py rewrite   # Qwen3 on the HPC, cached
    docker compose run --rm ml python scripts/exp_query_rewrite.py score     # retrieval, gate off
    docker compose run --rm ml python scripts/exp_query_rewrite.py report    # gate rules, 5-fold
    docker compose run --rm ml python scripts/exp_query_rewrite.py answers   # out-of-scope items that pass

Questions: the 77 gold v1 items plus JTKSM's official Malay wording of the
gold items that have one (id "<id>-ms"). Each is rewritten once with the
author's prompt (src/evaluation/rewrite.py), then retrieved twice with the
gate off: original wording and rewrite. Nothing here changes the live system.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from statistics import mean

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.evaluation.calibration import roc_auc  # noqa: E402
from src.evaluation.gate_rules import MIN_OOS_DECLINED, RULES, STOPPED, Scored, kfold  # noqa: E402
from src.evaluation.retrieval_eval import hit_at_k, reciprocal_rank  # noqa: E402
from src.evaluation.rewrite import REWRITE_PROMPT, added_numbers, malay_variants, rewrite_query  # noqa: E402
from src.generation.llm import SessionExpired  # noqa: E402

GOLD = Path("data/eval/gold_set.jsonl")
FAQ_CSV = Path("data/eval/faq_candidates_all.csv")
RUNS = Path("data/eval/runs")
REWRITES = RUNS / "2026-10-21_rewrite_rewrites.jsonl"
RECORDS = RUNS / "2026-10-21_rewrite_records.jsonl"
MODE = "hybrid_rerank"


def _jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def questions() -> list[dict]:
    gold = _jsonl(GOLD)
    return [{**g, "parent": g["id"]} for g in gold] + malay_variants(gold, FAQ_CSV)


def stage_rewrite() -> None:
    from dotenv import load_dotenv
    from src.generation.llm import build_chat_model

    load_dotenv(override=True)
    config = yaml.safe_load(Path("config/config.yaml").read_text(encoding="utf-8"))
    settings = {**config["generation"], "max_tokens": 100}
    chain = REWRITE_PROMPT | build_chat_model(settings, os.environ)
    items = questions()
    done = {r["id"] for r in _jsonl(REWRITES)} if REWRITES.exists() else set()
    with REWRITES.open("a", encoding="utf-8") as out:
        for item in items:
            if item["id"] in done:
                continue
            try:
                rewrite = rewrite_query(chain, item["question"], retries=settings["retries"])
            except SessionExpired as error:
                print(f"{error}\n{len(done)} of {len(items)} rewritten; rerun the same command to continue.")
                sys.exit(2)
            record = {"id": item["id"], "parent": item["parent"], "question": item["question"], "rewrite": rewrite,
                      "added_numbers": added_numbers(item["question"], rewrite)}
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()
            done.add(item["id"])
    rewrites = _jsonl(REWRITES)
    flagged = [r["id"] for r in rewrites if r["added_numbers"]]
    print(f"{len(rewrites)} rewrites -> {REWRITES}; added numbers in {len(flagged)}: {flagged}")


def stage_score() -> None:
    from src.retrieval.pipeline import Retriever

    retriever = Retriever.from_config()
    rewrites = {r["id"]: r["rewrite"] for r in _jsonl(REWRITES)}
    items = questions()
    missing = [i["id"] for i in items if i["id"] not in rewrites]
    if missing:
        sys.exit(f"run the rewrite stage first; missing rewrites for {missing}")
    with RECORDS.open("w", encoding="utf-8") as out:
        for item in items:
            for variant, text in (("orig", item["question"]), ("rew", rewrites[item["id"]])):
                result = retriever.retrieve(text, item["region"], MODE, gate=False)
                record = {
                    "id": item["id"], "variant": variant,
                    "gate_score": STOPPED if result.gate_score is None else result.gate_score,
                    "abstain_reason": result.abstain_reason,
                    "ranked": [c.chunk_id for c in result.chunks if c.added_because == "retrieved"],
                    "final": [c.chunk_id for c in result.chunks],
                    "result": result.model_dump(),
                }
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
    records = _jsonl(RECORDS)
    stopped = sorted({r["id"] for r in records if r["abstain_reason"] == "language"})
    print(f"{len(records)} records -> {RECORDS}; language-stopped: {stopped}")


REPORT = RUNS / "2026-10-21_rewrite_report.json"
ACT_NAME = re.compile(r"\b(?:Act|Ordinance|Regulations?)\b")
ACT_NAME_ANY = re.compile(r"\b(?:Act|Ordinance|Regulations?|Akta|Ordinan|Peraturan|IRA|EA)\b")


def _scored_items(gold: dict[str, dict], records: list[dict]) -> list[Scored]:
    """Gold in-scope and out-of-scope items, plus in-scope Malay variants on their parent's fold."""
    score = {(r["id"], r["variant"]): r["gate_score"] for r in records}
    items = []
    for item in questions():
        parent = gold[item["parent"]]
        if parent["scope_class"] == "external":
            continue
        items.append(Scored(id=item["id"], in_scope=parent["scope_class"] == "in_scope",
                            orig=score[(item["id"], "orig")], rew=score[(item["id"], "rew")], fold_of=item["parent"]))
    return items


def _retrieval_quality(gold: dict[str, dict], records: list[dict]) -> dict:
    ranked = {(r["id"], r["variant"]): r["ranked"] for r in records}
    rows = {"english": [], "malay": []}
    for item in questions():
        expected = gold[item["parent"]]["expected_chunk_ids"]
        if gold[item["parent"]]["scope_class"] != "in_scope" or not expected:
            continue
        rows["malay" if item["id"].endswith("-ms") else "english"].append((item, expected))

    def summary(pairs, variant):
        lists = [(ranked[(i["id"], variant)], e) for i, e in pairs]
        return {"n": len(lists), "hit@5": round(mean(hit_at_k(r, e, 5) for r, e in lists), 3),
                "mrr": round(mean(reciprocal_rank(r, e) for r, e in lists), 3)}

    english_parents = [(dict(i, id=i["parent"]), e) for i, e in rows["malay"]]
    return {"english_original": summary(rows["english"], "orig"), "english_rewrite": summary(rows["english"], "rew"),
            "malay_rewrite": summary(rows["malay"], "rew"), "malay_parents_english_original": summary(english_parents, "orig")}


def stage_report() -> None:
    gold = {g["id"]: g for g in _jsonl(GOLD)}
    records = _jsonl(RECORDS)
    rewrites = _jsonl(REWRITES)
    items = _scored_items(gold, records)
    gold_items = [i for i in items if i.fold_of == i.id]
    informal = {i.id for i in gold_items if i.in_scope and i.id.startswith("RDT-")}
    malay = {i.id for i in items if i.id.endswith("-ms")}

    def share_declined(decisions, ids):
        return round(sum(not decisions[i]["passed"] for i in ids) / len(ids), 3) if ids else None

    rules = {}
    for rule in RULES:
        result = kfold(rule, items)
        d = result["decisions"]
        rules[rule] = {
            "out_of_scope_declined": round(result["out_of_scope_declined"], 3),
            "in_scope_declined": round(result["in_scope_declined"], 3),
            "informal_in_scope_declined": share_declined(d, informal),
            "malay_in_scope_declined": share_declined(d, malay),
            "out_of_scope_passing": sorted((i.id, d[i.id]["source"]) for i in gold_items
                                           if not i.in_scope and d[i.id]["passed"]),
            "in_scope_declined_ids": sorted(i.id for i in gold_items if i.in_scope and not d[i.id]["passed"]),
            "fold_params": result["fold_params"],
            "decisions": d,
        }
    pairs = lambda f: [(f(i), i.in_scope) for i in gold_items]  # noqa: E731
    report = {
        "items": {"in_scope": sum(i.in_scope for i in gold_items), "out_of_scope": sum(not i.in_scope for i in gold_items),
                  "informal": len(informal), "malay": len(malay)},
        "min_out_of_scope_declined": MIN_OOS_DECLINED,
        "auc": {"orig": round(roc_auc(pairs(lambda i: i.orig)), 3), "rew": round(roc_auc(pairs(lambda i: i.rew)), 3),
                "max": round(roc_auc(pairs(lambda i: max(i.orig, i.rew))), 3)},
        "retrieval": _retrieval_quality(gold, records),
        "rewrite_checks": {
            "added_numbers": [r["id"] for r in rewrites if r["added_numbers"]],
            "added_act_names": [r["id"] for r in rewrites
                                if ACT_NAME.search(r["rewrite"]) and not ACT_NAME_ANY.search(r["question"])],
        },
        "rules": rules,
    }
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    print(f"items: {report['items']} | AUC {report['auc']}")
    print(f"retrieval: {report['retrieval']}")
    print(f"{'rule':10} {'OOS declined':>12} {'in-scope wrong':>14} {'informal':>9} {'Malay':>6}  out-of-scope passing")
    for rule, r in rules.items():
        print(f"{rule:10} {r['out_of_scope_declined']:>12.3f} {r['in_scope_declined']:>14.3f} "
              f"{r['informal_in_scope_declined']:>9.3f} {r['malay_in_scope_declined']:>6.3f}  {r['out_of_scope_passing']}")
    print(f"-> {REPORT}")


STAGES = {"rewrite": stage_rewrite, "score": stage_score, "report": stage_report}


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in STAGES:
        sys.exit(f"usage: python scripts/exp_query_rewrite.py {{{'|'.join(STAGES)}}}")
    STAGES[sys.argv[1]]()


if __name__ == "__main__":
    main()
