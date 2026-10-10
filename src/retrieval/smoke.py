"""Smoke checks for the M3 retrieval pipeline.

    docker compose run --rm ml python -m src.retrieval.smoke

Fixed questions with a behaviour a working pipeline must show: amendment
links followed, section lookups, the language gate, abstention, the
territory flag. Every check also requires that no chunk falls outside the
region and that no result exceeds the chunk cap. Sanity, not evaluation:
that is RAGAS and the abstention rates on the gold set.

Report: data/processed/index/retrieval_smoke_report.json. Exit 1 on failure.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src.retrieval.schema import RetrievalResult

REPORT = Path("data/processed/index/retrieval_smoke_report.json")


def matches(chunk_id: str, prefix: str) -> bool:
    """Whole id or followed by "_": "IRA1967_s5" must not match "IRA1967_s59_1"."""
    return chunk_id == prefix or chunk_id.startswith(prefix + "_")


def _has(result: RetrievalResult, prefix: str, retrieved_only: bool = False, top: int | None = None) -> bool:
    chunks = [c for c in result.chunks if not retrieved_only or c.added_because == "retrieved"]
    if top is not None:
        chunks = [c for c in chunks if c.rank is not None and c.rank <= top]
    return any(matches(c.chunk_id, prefix) for c in chunks)


@dataclass(frozen=True)
class Check:
    name: str
    query: str
    region: str | None
    expect: Callable[[RetrievalResult], bool]
    why: str


CHECKS = [
    Check("Sarawak amendment link", "maternity leave", "sarawak",
          lambda r: _has(r, "SWK76_s84") and _has(r, "A1754_s24"),
          "superseded Cap. 76 s.84 must arrive with A1754 s.24"),
    Check("Sabah maternity", "how many days of maternity leave", "sabah",
          lambda r: _has(r, "SBH67_s2_1_def_eligible_period", top=5),
          "the 98-day definition in the top 5"),
    # Not rank 1: EA s.100(4) ("fails to grant ... annual leave ... under
    # section 60E") is a fair rank 1 for the bare query (2026-10-10 run).
    Check("section lookup", "section 60E", None,
          lambda r: _has(r, "EA1955_s60E", top=5), "EA s.60E in the top 5"),
    Check("short section lookup", "what does section 92 of the Employment Act say", "peninsular",
          lambda r: _has(r, "EA1955_s92"), "an in-force offence section, found by number"),
    Check("deleted section lookup", "what does section 30 of the Employment Act say", "peninsular",
          lambda r: _has(r, "EA1955_s30"),
          "placeholder kept out of dense search must still be found by number (BM25)"),
    Check("Malay stopped", "cuti bersalin berapa hari", "sabah",
          lambda r: r.abstained and r.abstain_reason == "language", "language gate"),
    Check("mixed passes", "Can I claim cuti sakit?", "peninsular",
          lambda r: r.abstain_reason != "language", "English mixed with Malay is not stopped"),
    Check("out of scope", "can I bring my dog to work", None,
          lambda r: r.abstained and r.abstain_reason == "low_score", "reranker gate"),
    Check("no region, several territories", "how many days of maternity leave", None,
          lambda r: r.multiple_jurisdictions, "answer differs by territory"),
    Check("region given, one territory", "how many days of maternity leave", "peninsular",
          lambda r: not r.multiple_jurisdictions and not r.abstained, "flag only without a region"),
    Check("Sabah has no EA", "how many days of annual leave am I entitled to", "sabah",
          lambda r: not r.abstained, "EA must not appear (checked for every query)"),
    Check("Sarawak has no EA", "how many days of annual leave am I entitled to", "sarawak",
          lambda r: not r.abstained, "EA must not appear (checked for every query)"),
]


def run() -> dict:
    from src.retrieval.pipeline import Retriever

    retriever = Retriever.from_config()
    regions, cap = retriever.settings["regions"], retriever.settings["max_chunks"]
    results = []
    for check in CHECKS:
        result = retriever.retrieve(check.query, check.region)
        allowed = regions[check.region] if check.region else None
        leaked = [c.chunk_id for c in result.chunks if allowed is not None and c.jurisdiction not in allowed]
        passed = check.expect(result) and not leaked and len(result.chunks) <= cap
        results.append({
            "name": check.name, "query": check.query, "region": check.region, "why": check.why,
            "passed": passed, "wrong_jurisdiction": leaked, "abstained": result.abstained,
            "abstain_reason": result.abstain_reason, "gate_score": result.gate_score,
            "multiple_jurisdictions": result.multiple_jurisdictions,
            "chunks": [{"chunk_id": c.chunk_id, "rank": c.rank, "score": c.score, "added_because": c.added_because,
                        "linked_from": c.linked_from, "status": c.status} for c in result.chunks],
        })
    report = {"index_version": retriever.index_version, "checks": results,
              "passed": sum(r["passed"] for r in results), "total": len(results)}
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def main() -> int:
    report = run()
    for r in report["checks"]:
        mark = "PASS" if r["passed"] else "FAIL"
        where = f"[{r['region'] or 'all'}]"
        gate = "-" if r["gate_score"] is None else f"{r['gate_score']:.3f}"
        state = f"abstained ({r['abstain_reason']})" if r["abstained"] else f"{len(r['chunks'])} chunks"
        print(f"{mark}  {r['name']:32} {where:13} gate {gate:6}  {state}")
        if not r["passed"]:
            for c in r["chunks"]:
                print(f"        {c['rank'] or '+':>2}  {c['chunk_id']:34} {c['added_because']}")
    print(f"\n{report['passed']}/{report['total']} checks passed (index {report['index_version']})")
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
