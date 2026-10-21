"""LLM query rewrite for the offline experiment (plan 2026-10-21-query-rewrite-experiment).

The user's question is rewritten into the wording statutes use, so that
retrieval and the reranker gate see a fair question ("boss havent send me
any payment" -> "employer", "wages"). The rewrite is used for retrieval
only; answers are generated for the user's original question.

The prompt is the author's, verbatim, plus a line asking for English and a line forbidding Act
names the user did not state (see REWRITE_RULES). A rewrite that adds numbers the user
did not state breaks that prompt; added_numbers() flags it for the hand
check rather than trusting it.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate

from src.generation.llm import invoke_with_retry

REWRITE_RULES = ("Rewrite the user's question into formal Malaysian employment-law terms\n"
                 "for searching statutes. Fix spelling. Translate Malay/Manglish words.\n"
                 "Do NOT answer the question. Do NOT add facts, numbers, or legal\n"
                 "conclusions that the user did not state. Output one sentence only."
                 # Added 2026-10-21: the author's prompt alone gave Malay rewrites for 82 of 97
                 # questions ("Malaysian" read as Bahasa Malaysia); the agreed design is English.
                 "\nWrite the rewritten question in English."
                 # Added 2026-10-21 (author agreed): with the English line, 21 of 97 rewrites named
                 # an Act the user never stated, one of them invented ("Minimum Wages Act 1961").
                 "\nDo NOT name an Act or section that the user did not state.")

REWRITE_PROMPT = ChatPromptTemplate.from_messages([("system", REWRITE_RULES), ("human", "{question}")])

LABEL = re.compile(r"^(?:rewritten|formal|rephrased)?\s*(?:question|query)\s*:\s*", re.IGNORECASE)
UNITS = "one|two|three|four|five|six|seven|eight|nine"
TEENS = "ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen"
TENS = "twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety"
NUMBER = re.compile(rf"\b(?:\d+(?:\.\d+)?|(?:{TENS})(?:-(?:{UNITS}))?|{TEENS}|{UNITS}|hundred|thousand)\b", re.IGNORECASE)


def clean_rewrite(text: str) -> str:
    """The rewritten sentence alone: first non-empty line, no label, no surrounding quotes."""
    for line in text.splitlines():
        line = LABEL.sub("", line.strip()).strip().strip("\"'\u201c\u201d").strip()
        if line:
            return line
    raise ValueError("empty rewrite")


def added_numbers(original: str, rewrite: str) -> list[str]:
    """Numbers (digits or words) in the rewrite that the original does not contain."""
    present = {n.lower() for n in NUMBER.findall(original)}
    return list(dict.fromkeys(n for n in NUMBER.findall(rewrite) if n.lower() not in present))


def rewrite_query(chain, question: str, retries: int = 3) -> str:
    """One rewrite through REWRITE_PROMPT | model."""
    return clean_rewrite(invoke_with_retry(chain, {"question": question}, retries=retries).text)


def malay_variants(gold: list[dict], csv_path: Path) -> list[dict]:
    """Gold items asked with JTKSM's official Malay wording (question_ms), id "<id>-ms"."""
    with Path(csv_path).open(encoding="utf-8-sig", newline="") as f:
        malay = {row["id"]: row["question_ms"].strip() for row in csv.DictReader(f) if (row.get("question_ms") or "").strip()}
    return [{**item, "id": f"{item['id']}-ms", "parent": item["id"], "question": malay[item["id"]]}
            for item in gold if item["id"] in malay]
