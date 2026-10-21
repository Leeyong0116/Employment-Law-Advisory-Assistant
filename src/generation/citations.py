"""Markers in the answer -> citations from chunk metadata (M4).

The model writes [n] after a statement, where n is a context block. Here
each n is looked up in the blocks, the markers are renumbered in order of
first use, and the citation is copied from that block's metadata. A number
with no block is removed from the text and recorded, never guessed.

The checks below measure traceability (is each statement tied to a source
the model was shown?), not legal correctness (CLAUDE.md, core contribution 2).
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from src.generation.schema import Citation
from src.retrieval.schema import RetrievedChunk

MARKER = re.compile(r"(\s*)\[\s*(\d+(?:\s*[-–,]\s*\d+)*)\s*\]")
MAX_RANGE = 20
MIN_SENTENCE_WORDS = 6
# Sentence ends: whitespace after . ! ? or a closing marker, before a capital, quote or bracket.
SENTENCE_BREAK = re.compile(r"(?<=[.!?\]])\s+(?=[A-Z\"'(])")
SECTION_MENTION = re.compile(
    r"\b(?:sections?|subsections?|regulations?|reg\.|ss?\.)\s?\d+[A-Z]*(?:\(\w+\))*", re.IGNORECASE)
STATUTE_MENTION = re.compile(r"\b(?:[A-Z][a-z]+ )+(?:Act|Ordinance)\b(?: \d{4})?|\b(?:EA|IRA)\b(?: \d{4})?|\bCap\. ?\d+")


class Resolved(BaseModel):
    answer: str
    citations: list[Citation]
    invalid_markers: list[int]
    uncited_sentences: int
    provision_mentions: list[str]


def _numbers(group: str) -> list[int]:
    numbers: list[int] = []
    for part in group.split(","):
        ends = [int(x) for x in re.split(r"\s*[-–]\s*", part.strip())]
        low, high = min(ends), max(ends)
        numbers += list(range(low, high + 1)) if high - low <= MAX_RANGE else ends
    return list(dict.fromkeys(numbers))


def _uncited_sentences(text: str) -> int:
    count = 0
    for line in text.splitlines():
        for sentence in SENTENCE_BREAK.split(line.strip()):
            if not sentence or sentence.endswith(":") or MARKER.search(sentence):
                continue
            if len(re.findall(r"[A-Za-z]+", sentence)) >= MIN_SENTENCE_WORDS:
                count += 1
    return count


def _mentions(text: str) -> list[str]:
    found = [(m.start(), m.group()) for pattern in (SECTION_MENTION, STATUTE_MENTION) for m in pattern.finditer(text)]
    cleaned = (re.sub(r"^(?:The|Under|In|By) ", "", mention) for _, mention in sorted(found))
    return list(dict.fromkeys(cleaned))


def resolve(text: str, blocks: list[RetrievedChunk]) -> Resolved:
    """Renumber markers by first use and build citations from the blocks they name."""
    assigned: dict[int, int] = {}   # block number -> citation number
    invalid: list[int] = []

    def rewrite(match: re.Match) -> str:
        kept = []
        for n in _numbers(match.group(2)):
            if 1 <= n <= len(blocks):
                kept.append(assigned.setdefault(n, len(assigned) + 1))
            elif n not in invalid:
                invalid.append(n)
        if not kept:
            return ""
        return match.group(1) + "".join(f"[{c}]" for c in dict.fromkeys(kept))

    answer = MARKER.sub(rewrite, text).strip()
    citations = [Citation.from_chunk(number, blocks[block - 1]) for block, number in assigned.items()]
    return Resolved(answer=answer, citations=citations, invalid_markers=invalid,
                    uncited_sentences=_uncited_sentences(answer), provision_mentions=_mentions(answer))
