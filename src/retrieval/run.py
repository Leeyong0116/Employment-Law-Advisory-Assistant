"""Run retrieval over a question file and save the results.

    python -m src.retrieval.run questions.jsonl results.jsonl [--mode hybrid] [--no-gate]

Input lines: {"id": ..., "question": ..., "region": "sabah" | null, ...}.
Output lines: {"id": ..., "result": RetrievalResult}.

Retrieval is deterministic, so its output can be saved once on the local
machine (where the database lives) and handed to generation and evaluation
on the HPC.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.retrieval.pipeline import MODES, Retriever


def main() -> None:
    parser = argparse.ArgumentParser(description="Run retrieval over a question file.")
    parser.add_argument("questions", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--mode", choices=MODES, default="hybrid_rerank")
    parser.add_argument("--no-gate", action="store_true", help="never abstain on score (evaluation runs)")
    args = parser.parse_args()

    questions = [json.loads(line) for line in args.questions.open(encoding="utf-8") if line.strip()]
    retriever = Retriever.from_config()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as out:
        for item in questions:
            result = retriever.retrieve(item["question"], item.get("region"), args.mode, gate=not args.no_gate)
            out.write(json.dumps({"id": item["id"], "result": result.model_dump()}, ensure_ascii=False) + "\n")
    print(f"{len(questions)} questions, mode {args.mode}, gate {'off' if args.no_gate else 'on'} -> {args.output}")


if __name__ == "__main__":
    main()
