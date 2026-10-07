"""Validation of the ingested corpus.

The CP1 requirement: every section in a source's ARRANGEMENT OF SECTIONS
must appear in at least one chunk. The expected list comes from toc.py,
which reads only the contents pages, so this is a check on the parser and
not a restatement of it.

Beyond coverage, the checks guard the failure modes that would break
citation traceability without any error: duplicate chunk ids, editorial
text served as statute, a chunk with nothing to cite, and amendment links
that point nowhere.
"""

from __future__ import annotations

from collections import Counter

from src.ingestion.toc import TocEntry

# Text that must never reach a chunk's content: editorial footnotes, Sarawak
# amendment tags, and running headers.
_EDITORIAL = ("*NOTE", "NOTE—", "[Am. Act", "[Sub. Act", "[Ins. Act", "CAP. 76 (1948 ED.)",
              "FOR REFERENCE ONLY", "Sarawak Lawnet")
_REQUIRED = ("citation", "content", "source_page", "jurisdiction")


def check_coverage(inventory: list[TocEntry], chunks: list[dict]) -> list[str]:
    """Every section and schedule the contents list must have a chunk."""
    have = {(c["doc_id"], c["section"]) for c in chunks}
    return [
        f"{entry.doc_id}: {'s.' if entry.kind == 'section' else ''}{entry.section} "
        "listed in ARRANGEMENT OF SECTIONS has no chunk"
        for entry in inventory
        if (entry.doc_id, entry.section) not in have
    ]


def check_integrity(chunks: list[dict]) -> list[str]:
    problems: list[str] = []
    counts = Counter(c["chunk_id"] for c in chunks)
    problems += [f"duplicate chunk_id {chunk_id}" for chunk_id, n in counts.items() if n > 1]

    ids = set(counts)
    for chunk in chunks:
        chunk_id = chunk["chunk_id"]
        for marker in _EDITORIAL:
            if marker in (chunk.get("content") or ""):
                problems.append(f"{chunk_id}: editorial text {marker!r} in content")
        for field in _REQUIRED:
            if chunk.get(field) in (None, ""):
                problems.append(f"{chunk_id}: missing {field}")
        for field in ("amended_by", "amends"):
            for target in chunk.get(field) or []:
                if target not in ids:
                    problems.append(f"{chunk_id}: {field} points at unknown chunk {target}")
    return problems
