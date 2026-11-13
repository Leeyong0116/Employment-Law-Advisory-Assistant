"""M6 Task 7: the final run of the demo questions through the real API (2026-11-13).

    docker compose run --rm ml python -m scripts.frontend_demo_run

One question per display state and per region. Goes through FastAPI's TestClient (no port),
saves every response to frontend/src/test/fixtures/demo/ so the frontend tests render the
real output, and checks what the screen depends on:
  - every citation's jurisdiction is the asked region or Malaysia (core contribution 4),
  - every [n] in the answer has a citation and every citation is used,
  - the LIMITS line never stays in the answer text,
  - every cited provision opens in the source panel (/api/provisions returns 200).
Sanity for the demo, not evaluation (that is the gold set).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

OUT = Path("frontend/src/test/fixtures/demo")
QUESTIONS = [
    ("annual_leave", "How many days of annual leave do I get?", "peninsular"),
    ("sarawak_maternity", "How long is maternity leave?", "sarawak"),
    ("sabah_sick_leave", "How many days of paid sick leave am I entitled to?", "sabah"),
    ("dismissal", "my boss fired me without any notice period", "peninsular"),
    ("unfair_dismissal", "How do I make a representation if I was dismissed without just cause?", "peninsular"),
    ("epf", "How do I withdraw my EPF savings?", "peninsular"),
    ("malay", "Berapa hari cuti tahunan saya?", "sarawak"),
    ("minimum_wage", "What is the minimum wage in Malaysia?", "sabah"),
]


def main() -> int:
    from src.api.app import build

    regions = yaml.safe_load(Path("config/config.yaml").read_text(encoding="utf-8"))["retrieval"]["regions"]
    client = TestClient(build())
    OUT.mkdir(parents=True, exist_ok=True)
    failures = 0
    for name, query, region in QUESTIONS:
        response = client.post("/api/ask", json={"query": query, "region": region})
        answer = response.json()
        (OUT / f"{name}.json").write_text(json.dumps(answer, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        problems = []
        if response.status_code != 200:
            problems.append(f"HTTP {response.status_code}")
        citations = answer.get("citations", [])
        leaks = [c["citation"] for c in citations if c["jurisdiction"] not in regions[region]]
        if leaks:
            problems.append(f"outside {region}: {leaks}")
        used = {int(n) for n in re.findall(r"\[(\d+)\]", answer.get("answer") or "")}
        numbers = {c["number"] for c in citations}
        if used - numbers:
            problems.append(f"markers without citation {sorted(used - numbers)}")
        if numbers - used:
            problems.append(f"citations never used {sorted(numbers - used)}")
        if "LIMITS" in (answer.get("answer") or ""):
            problems.append("LIMITS left in the text")
        for c in citations:
            if client.get(f"/api/provisions/{c['chunk_id']}").status_code != 200:
                problems.append(f"provision {c['chunk_id']} does not open")

        failures += bool(problems)
        print(f"{'FAIL' if problems else 'PASS'}  {name:18s} {answer.get('status', '?'):21s} "
              f"citations {[c['citation'].split(', ')[-1] for c in citations]}  limits {'yes' if answer.get('limits') else 'no'}"
              + (f"  PROBLEMS {problems}" if problems else ""))
    print(f"\n{len(QUESTIONS) - failures}/{len(QUESTIONS)} passed -> {OUT}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
