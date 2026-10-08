"""Smoke checks: does the built index find the obvious answers?

    python -m src.indexing.smoke

A handful of fixed queries, each with the chunk(s) a working index must
return in its top 5. This proves the index works end to end (model,
database, BM25, jurisdiction filter); it does not measure retrieval
quality. That is RAGAS on the gold set, from M3.

Results go to data/processed/index/smoke_report.json. Exit status 1 if any
check fails.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

TOP_K = 5


@dataclass(frozen=True)
class Check:
    name: str
    query: str
    mode: str  # "dense" or "bm25"
    region: str | None
    expect_prefixes: tuple[str, ...]  # pass if any top-k chunk_id starts with one of these
    why: str


CHECKS = [
    Check("annual leave", "How many days of annual leave am I entitled to?", "dense", "peninsular",
          ("EA1955_s60E",), "plain-language question, no section number"),
    Check("section lookup", "section 60E", "bm25", None,
          ("EA1955_s60E",), "direct section-number lookup"),
    Check("Sabah maternity", "How many days of maternity leave do I get?", "dense", "sabah",
          ("SBH67_s83", "SBH67_s2_1_def_eligible_period"), "jurisdiction-filtered question"),
    Check("Sarawak maternity", "How many days of maternity leave do I get?", "dense", "sarawak",
          ("SWK76_s84", "A1754_s24", "SWK76_s2_1_def_eligible_period"), "principal text or its A1754 amendment"),
    Check("union dismissal", "Can my employer dismiss me for joining a trade union?", "dense", None,
          ("IRA1967_s5",), "IRA applies everywhere"),
    Check("essential services", "Which services count as essential services?", "dense", None,
          ("IRA1967_sch1",), "schedule chunk"),
    Check("fired without notice", "my boss fired me without telling me, is that allowed?", "dense", "peninsular",
          ("EA1955_s12", "EA1955_s13", "EA1955_s14", "EA1955_s11"),
          "BM25 finds nothing here (no word in common with the statute); dense must"),
]


def matches(chunk_id: str, prefixes: tuple[str, ...]) -> bool:
    """Whether a chunk belongs to an expected section.

    A plain prefix test is wrong: "IRA1967_s5" is a prefix of "IRA1967_s59_1".
    The prefix must be the whole id or be followed by "_".
    """
    return any(chunk_id == p or chunk_id.startswith(p + "_") for p in prefixes)


def _filters(config: dict, region: str | None) -> list[str] | None:
    return None if region is None else config["retrieval"]["regions"][region]


def run(config_path: str | Path = "config/config.yaml") -> dict:
    from src.indexing.bm25 import Bm25Index
    from src.indexing.embed import BgeM3Embedder
    from src.indexing.store import ChunkStore, connect

    config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    settings = config["indexing"]
    manifest = json.loads(Path(settings["manifest_path"]).read_text(encoding="utf-8"))
    chunks_path = Path(config["corpus"]["processed_dir"]) / "chunks.jsonl"
    chunks = {c["chunk_id"]: c for c in map(json.loads, chunks_path.open(encoding="utf-8"))}

    embedder = BgeM3Embedder(settings["embedding_model"], settings["embed_batch_size"])
    dense_queries = [c.query for c in CHECKS if c.mode == "dense"]
    try:
        vectors = dict(zip(dense_queries, embedder.encode(dense_queries)[0]))
    finally:
        embedder.close()
    bm25 = Bm25Index.load(settings["bm25_dir"])

    results = []
    with connect(config) as conn:
        store = ChunkStore(conn, settings["embedding_dim"])
        for check in CHECKS:
            allowed = _filters(config, check.region)
            if check.mode == "dense":
                hits = store.dense_search(vectors[check.query], TOP_K, allowed, manifest["index_version"])
            else:
                hits = bm25.search(check.query, TOP_K, allowed)
            top = [chunk_id for chunk_id, _ in hits]
            found = [c for c in top if matches(c, check.expect_prefixes)]
            leaked = [c for c in top if allowed is not None and chunks[c]["jurisdiction"] not in allowed]
            results.append({
                "name": check.name, "query": check.query, "mode": check.mode, "region": check.region,
                "why": check.why, "passed": bool(found) and not leaked,
                "rank_of_expected": top.index(found[0]) + 1 if found else None,
                "wrong_jurisdiction": leaked,
                "top": [{"chunk_id": c, "citation": chunks[c]["citation"], "score": round(s, 3)} for c, s in hits],
            })

    report = {"index_version": manifest["index_version"], "top_k": TOP_K, "checks": results,
              "passed": sum(r["passed"] for r in results), "total": len(results)}
    out = Path(settings["manifest_path"]).with_name("smoke_report.json")
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def main() -> int:
    report = run()
    for r in report["checks"]:
        mark = "PASS" if r["passed"] else "FAIL"
        where = f"[{r['region']}]" if r["region"] else "[all]"
        rank = f"rank {r['rank_of_expected']}" if r["rank_of_expected"] else "not in top 5"
        print(f"{mark}  {r['name']:22} {r['mode']:5} {where:13} {rank}")
        for hit in r["top"]:
            print(f"        {hit['score']:7.3f}  {hit['citation']}")
    print(f"\n{report['passed']}/{report['total']} checks passed (index {report['index_version']})")
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
