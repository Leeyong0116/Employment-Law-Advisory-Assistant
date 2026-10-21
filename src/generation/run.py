"""Generate answers for saved retrieval results.

    python -m src.generation.run retrieval.jsonl answers.jsonl

Input: the output of src.retrieval.run (lines {"id": ..., "result": RetrievalResult}).
Output lines: {"id": ..., "answer": GeneratedAnswer}, written and flushed one at a time.

Retrieval runs where the database lives; this step needs only the generator
server. The OOD session cookie expires after some hours, so a run can stop
partway: ids already in the output are skipped, and rerunning the same
command continues where it stopped.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.generation.answer import Answerer
from src.generation.llm import SessionExpired
from src.retrieval.schema import RetrievalResult


def _done_ids(output: Path) -> set[str]:
    if not output.exists():
        return set()
    return {json.loads(line)["id"] for line in output.open(encoding="utf-8") if line.strip()}


def run(items: list[dict], answerer, output: Path) -> int:
    """Answer every item not yet in output. Returns the number answered in this call."""
    done = _done_ids(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with output.open("a", encoding="utf-8") as out:
        for item in items:
            if item["id"] in done:
                continue
            answer = answerer.answer(RetrievalResult.model_validate(item["result"]))
            out.write(json.dumps({"id": item["id"], "answer": answer.model_dump()}, ensure_ascii=False) + "\n")
            out.flush()
            written += 1
    return written


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate answers for saved retrieval results.")
    parser.add_argument("retrieval", type=Path, help="output of python -m src.retrieval.run")
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)

    items = [json.loads(line) for line in args.retrieval.open(encoding="utf-8") if line.strip()]
    try:
        run(items, Answerer.from_config(), args.output)
    except SessionExpired as error:
        done = len(_done_ids(args.output) & {item["id"] for item in items})
        print(f"{error}\n{done} of {len(items)} answered so far in {args.output}; rerun the same command to continue.")
        sys.exit(2)
    print(f"{len(items)} of {len(items)} answered -> {args.output}")


if __name__ == "__main__":
    main()
