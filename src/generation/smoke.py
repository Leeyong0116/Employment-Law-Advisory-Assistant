"""Smoke checks for M4 generation, end to end (retrieval + the live generator).

    docker compose run --rm ml python -m src.generation.smoke

Needs the database (docker compose up -d) and the generator server
(GENERATOR_BASE_URL and a fresh OOD_COOKIE_SECRET in .env). Fixed questions
with a behaviour a working system must show: the amended Sarawak rule, the
EA regulations, territory separation, abstention without a model call.
Every answered check also requires that no citation falls outside the
region. Sanity, not evaluation: that is RAGAS on the gold set.

Report: data/processed/generation_smoke_report.json. Exit 1 on failure.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src.generation.schema import GeneratedAnswer
from src.retrieval.pipeline import NATIONWIDE
from src.retrieval.smoke import matches

REPORT = Path("data/processed/generation_smoke_report.json")


def cites(answer: GeneratedAnswer, prefix: str) -> bool:
    return any(matches(c.chunk_id, prefix) for c in answer.citations)


def territories(answer: GeneratedAnswer) -> set[str]:
    return {c.jurisdiction for c in answer.citations if c.jurisdiction != NATIONWIDE}


def leaked(answer: GeneratedAnswer, allowed: list[str] | None) -> list[str]:
    return [c.chunk_id for c in answer.citations if allowed is not None and c.jurisdiction not in allowed]


def _answered(answer: GeneratedAnswer) -> bool:
    return answer.status == "answered" and bool(answer.citations)


@dataclass(frozen=True)
class Check:
    name: str
    query: str
    region: str | None
    expect: Callable[[GeneratedAnswer], bool]
    why: str


CHECKS = [
    Check("Peninsular overtime rate", "What is the overtime pay rate on a normal working day?", "peninsular",
          lambda a: _answered(a) and cites(a, "EA1955_s60A_3"),
          "s. 60A(3) (stored under EA1955_s60A_3_def_overtime) sets 1.5 times the hourly rate"),
    Check("Peninsular overtime limit", "What is the maximum number of overtime hours an employee can work in a month?",
          "peninsular", lambda a: _answered(a) and cites(a, "OT1980_r2"), "Overtime Regulations reg. 2: 104 hours"),
    Check("Sarawak maternity, amended", "How many days of maternity leave do I get?", "sarawak",
          lambda a: _answered(a) and bool(re.search(r"\b98\b|ninety-eight", a.answer, re.IGNORECASE))
          and any(c.chunk_id.startswith("A1754_") for c in a.citations)
          and not re.search(r"\b(60|sixty) (consecutive )?days", a.answer, re.IGNORECASE),
          "A1754 s. 24 replaced Cap. 76 s. 84's 60 days with 98; the old figure must not be stated as current"),
    Check("Sabah annual leave", "How many days of annual leave am I entitled to?", "sabah",
          _answered, "Sabah or nationwide citations only (checked for every answered check)"),
    Check("maternity, no region", "How many days of maternity leave do I get?", None,
          lambda a: _answered(a) and len(territories(a)) > 1, "the answer differs by territory and must say so"),
    Check("out of scope", "How do I renew my passport?", "peninsular",
          lambda a: a.status == "abstained" and a.generator is None, "gate abstains; no model call"),
    Check("Malay stopped", "cuti bersalin berapa hari", "sabah",
          lambda a: a.status == "abstained" and a.abstention.reason == "language", "language gate; no model call"),
]


def run() -> dict:
    from src.generation.answer import Answerer
    from src.retrieval.pipeline import Retriever

    retriever, answerer = Retriever.from_config(), Answerer.from_config()
    regions = retriever.settings["regions"]
    results = []
    for check in CHECKS:
        answer = answerer.answer(retriever.retrieve(check.query, check.region))
        wrong = leaked(answer, regions[check.region] if check.region else None)
        results.append({"name": check.name, "query": check.query, "region": check.region, "why": check.why,
                        "passed": check.expect(answer) and not wrong, "wrong_jurisdiction": wrong,
                        "answer": answer.model_dump()})
    report = {"checks": results, "passed": sum(r["passed"] for r in results), "total": len(results)}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def main() -> int:
    report = run()
    for r in report["checks"]:
        a = r["answer"]
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['name']:28} {a['status']}")
        if a["answer"]:
            print("      " + a["answer"].replace("\n", "\n      "))
        for c in a["citations"]:
            print(f"      [{c['number']}] {c['citation']}  ({c['chunk_id']})")
    print(f"\n{report['passed']}/{report['total']} checks passed -> {REPORT}")
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
