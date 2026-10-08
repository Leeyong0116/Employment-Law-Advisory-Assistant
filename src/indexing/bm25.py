"""BM25 keyword index over the chunks.

The sparse half of hybrid retrieval. It matches exact words, so it finds
what the dense side is weak at: rare legal terms ("overtime", "Industrial
Court") and section numbers ("section 60E"). It cannot match a synonym
("fired" for "terminate"); that is the dense side's job.

What is indexed: citation + section title + content. The citation makes
section-number lookups work; the dense side still embeds content only, as
the CP1 schema fixes.

Ranking is deterministic: equal scores are broken by chunk_id, so the same
query always returns the same list (CLAUDE.md: deterministic retrieval).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import bm25s
import numpy as np

# "60e", "2(1)", "60i(1a)" stay whole, so a section-number query does not
# match every chunk that merely contains the digits.
_TOKEN = re.compile(r"\d+[a-z]*(?:\(\d+[a-z]?\))*|[a-z]+")
_STOPWORDS = frozenset(
    "a an the of to in on for and or is are be by my me i can do does if with at as it "
    "this that how many what am will from any s".split()
)


def tokenize(text: str) -> list[str]:
    """Lower-case tokens; a subsection reference also yields its section."""
    tokens: list[str] = []
    for token in _TOKEN.findall(text.lower()):
        if token in _STOPWORDS:
            continue
        tokens.append(token)
        if "(" in token:
            tokens.append(token.split("(")[0])
    return tokens


def index_text(chunk: dict) -> str:
    return " ".join(part for part in (chunk["citation"], chunk.get("section_title"), chunk["content"]) if part)


class Bm25Index:
    """BM25 over all chunks, with an optional jurisdiction filter."""

    def __init__(self, retriever: bm25s.BM25, chunk_ids: list[str], jurisdictions: list[str]):
        self._retriever = retriever
        self.chunk_ids = chunk_ids
        self.jurisdictions = np.array(jurisdictions)

    @classmethod
    def build(cls, chunks: list[dict]) -> "Bm25Index":
        retriever = bm25s.BM25()
        retriever.index([tokenize(index_text(c)) for c in chunks], show_progress=False)
        return cls(retriever, [c["chunk_id"] for c in chunks], [c["jurisdiction"] for c in chunks])

    def search(self, query: str, k: int = 20, jurisdictions: list[str] | None = None) -> list[tuple[str, float]]:
        """Top k (chunk_id, score); chunks with no query word are never returned."""
        tokens = [t for t in tokenize(query) if t in self._retriever.vocab_dict]
        if not tokens:
            return []
        scores = np.asarray(self._retriever.get_scores(tokens), dtype=float)
        allowed = scores > 0
        if jurisdictions is not None:
            allowed &= np.isin(self.jurisdictions, jurisdictions)
        hits = [(self.chunk_ids[i], float(scores[i])) for i in np.flatnonzero(allowed)]
        hits.sort(key=lambda hit: (-hit[1], hit[0]))
        return hits[:k]

    def save(self, directory: str | Path) -> None:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self._retriever.save(str(directory / "bm25s"))
        (directory / "chunks.json").write_text(
            json.dumps({"chunk_ids": self.chunk_ids, "jurisdictions": self.jurisdictions.tolist()}),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, directory: str | Path) -> "Bm25Index":
        directory = Path(directory)
        retriever = bm25s.BM25.load(str(directory / "bm25s"))
        meta = json.loads((directory / "chunks.json").read_text(encoding="utf-8"))
        return cls(retriever, meta["chunk_ids"], meta["jurisdictions"])
