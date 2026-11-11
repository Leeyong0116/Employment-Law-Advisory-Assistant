"""Print full answers for a few questions through the real pipeline (manual check, no files written).

    docker compose run --rm -e PYTHONPATH=/app ml python scripts/answer_check.py
"""
from src.generation.answer import Answerer
from src.retrieval.pipeline import Retriever

import sys

QUESTIONS = [(sys.argv[1], sys.argv[2])] if len(sys.argv) > 2 else [
    ("my boss fired me without any notice period", "peninsular"),
    ("How many days of annual leave do I get?", "peninsular"),
    ("How long is maternity leave?", "sarawak"),
]

retriever, answerer = Retriever.from_config(), Answerer.from_config()
for question, region in QUESTIONS:
    result = retriever.retrieve(question, region)
    answer = answerer.answer(result)
    print("=" * 100, f"\nQ: {question} ({region})  status={answer.status}  prompt={answer.generator.prompt_version if answer.generator else '-'}")
    print("context:", [c.citation.split(", ")[-1] for c in result.chunks])
    print(answer.answer)
    print("LIMITS ->", answer.limits)
    print("citations:", [f"[{c.number}] {c.citation}" for c in answer.citations])
