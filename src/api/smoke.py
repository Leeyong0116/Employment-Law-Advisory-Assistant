"""Smoke checks for the M5 API, end to end through HTTP on the real engine.

    docker compose run --rm ml python -m src.api.smoke

Needs the database (docker compose up -d) and the generator server
(GENERATOR_BASE_URL and a fresh OOD_COOKIE_SECRET in .env). Goes through
FastAPI's TestClient, so it exercises routing, validation and serialisation
without opening a port. Sanity, not evaluation: that is RAGAS on the gold set.

Report: data/processed/api_smoke_report.json. Exit 1 on failure.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

REPORT = Path("data/processed/api_smoke_report.json")
MATERNITY = "How many days of maternity leave do I get?"   # the src.generation.smoke question
MALAY = "cuti bersalin berapa hari"
OUT_OF_SCOPE_GOLD_ID = "JPPM-012"   # in_scope false; gate abstained (low_score) in the m4-v2 gold run
SARAWAK_OK = {"Sarawak", "Malaysia"}


def _events(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def run() -> dict:
    from src.api.app import build

    config = yaml.safe_load(Path("config/config.yaml").read_text(encoding="utf-8"))
    manifest = json.loads(Path(config["indexing"]["manifest_path"]).read_text(encoding="utf-8"))
    chunks_path = Path(config["corpus"]["processed_dir"]) / "chunks.jsonl"
    gold = {g["id"]: g for g in map(json.loads, Path(config["evaluation"]["gold_set_path"]).open(encoding="utf-8"))}
    out_of_scope = gold[OUT_OF_SCOPE_GOLD_ID]

    client = TestClient(build())
    checks = []

    def check(name: str, passed: bool, detail: dict):
        checks.append({"name": name, "passed": bool(passed), **detail})

    health = client.get("/api/health")
    check("health", health.status_code == 200 and health.json()["index_version"] == manifest["index_version"],
          {"status_code": health.status_code, "body": health.json()})

    meta = client.get("/api/meta").json()
    check("meta", len(meta["statutes_held"]) == len(config["corpus"]["documents"]) and len(meta["regions"]) == 3,
          {"statutes_held": len(meta["statutes_held"]), "regions": sorted(meta["regions"])})

    body = {"query": MATERNITY, "region": "sarawak"}
    ask = client.post("/api/ask", json=body)
    answer = ask.json()
    ids = [c["chunk_id"] for c in answer.get("citations", [])]
    outside = [c["chunk_id"] for c in answer.get("citations", []) if c["jurisdiction"] not in SARAWAK_OK]
    check("Sarawak maternity via /api/ask",
          ask.status_code == 200 and answer["status"] == "answered"
          and any(i.startswith("A1754_") for i in ids) and not outside,
          {"status_code": ask.status_code, "status": answer.get("status"), "citations": ids, "outside_region": outside})

    stream = client.post("/api/ask/stream", json=body)
    events = _events(stream.text)
    names = [e for e, _ in events]
    stream_ids = [c["chunk_id"] for c in events[-1][1].get("citations", [])] if names[-1] == "answer" else None
    check("same question via /api/ask/stream",
          names == ["stage", "retrieval", "stage", "answer"] and stream_ids == ids,
          {"events": names, "citations": stream_ids})

    malay = client.post("/api/ask", json={"query": MALAY, "region": "sabah"})
    m = malay.json()
    check("Malay question abstains (language)",
          malay.status_code == 200 and m["status"] == "abstained" and m["abstention"]["reason"] == "language",
          {"status_code": malay.status_code, "status": m.get("status")})

    oos = client.post("/api/ask", json={"query": out_of_scope["question"], "region": out_of_scope["region"]})
    o = oos.json()
    check(f"out of scope {OUT_OF_SCOPE_GOLD_ID} abstains (low_score)",
          oos.status_code == 200 and o["status"] == "abstained" and o["abstention"]["reason"] == "low_score",
          {"status_code": oos.status_code, "status": o.get("status")})

    if ids:
        provision = client.get(f"/api/provisions/{ids[0]}")
        source = next(c for c in map(json.loads, chunks_path.open(encoding="utf-8")) if c["chunk_id"] == ids[0])
        check("provision text equals chunks.jsonl",
              provision.status_code == 200 and provision.json()["content"] == source["content"],
              {"chunk_id": ids[0], "section_chunk_ids": provision.json().get("section_chunk_ids")})
    else:
        check("provision text equals chunks.jsonl", False, {"reason": "no citation to look up"})

    report = {"checks": checks, "passed": sum(c["passed"] for c in checks), "total": len(checks),
              "answer": answer}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def main() -> int:
    report = run()
    for c in report["checks"]:
        detail = {k: v for k, v in c.items() if k not in ("name", "passed")}
        print(f"{'PASS' if c['passed'] else 'FAIL'}  {c['name']:40} {json.dumps(detail, ensure_ascii=False)}")
    print(f"\n{report['passed']}/{report['total']} checks passed -> {REPORT}")
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
