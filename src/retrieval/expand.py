"""Add linked chunks to the retrieved ones, by metadata lookup only.

Three rules, in priority order:

1. Forward amendment. A retrieved chunk with `amended_by` (Sarawak Cap. 76
   text changed by Act A1754) brings the amending A1754 chunk. Without it
   the answer comes from repealed wording, so this rule goes first.
2. Same-section definition. A retrieved chunk in section X brings the
   definition chunks of section X in the same document (Sarawak s.84(11)
   defines a term s.84(1) uses). Not for the Act-wide interpretation
   section (s.2), which holds up to 48 definitions.
3. Reverse amendment. A retrieved A1754 chunk brings the principal text it
   amends, at most `reverse_cap` chunks in document order, because an
   instruction such as "substitute for subsection (1)" is unreadable alone.

Links are one hop from retrieved chunks only. Cross-references
(`cross_references_internal`) are not followed in M3. All of this is
deterministic: no search, no model.

A total cap (`max_chunks`, retrieved included) bounds the context; what the
cap drops is counted, not hidden.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Added:
    chunk_id: str
    added_because: str  # "amendment_of" | "definition_for" | "amended_by"
    linked_from: str


@dataclass
class Expansion:
    added: list[Added] = field(default_factory=list)
    dropped: int = 0


class Expander:
    def __init__(self, chunks: dict[str, dict], max_chunks: int = 12, reverse_cap: int = 3,
                 interpretation_section: str = "2"):
        """`chunks` must be in document order (as read from chunks.jsonl)."""
        self.chunks, self.max_chunks, self.reverse_cap = chunks, max_chunks, reverse_cap
        self.interpretation_section = interpretation_section
        self.order = {chunk_id: i for i, chunk_id in enumerate(chunks)}
        self.definitions: dict[tuple[str, str], list[str]] = defaultdict(list)
        for chunk_id, chunk in chunks.items():
            if chunk["chunk_type"] == "definition" and chunk.get("section"):
                self.definitions[(chunk["doc_id"], chunk["section"])].append(chunk_id)

    def _forward(self, chunk_id: str) -> list[str]:
        return list(self.chunks[chunk_id].get("amended_by") or [])

    def _definitions(self, chunk_id: str) -> list[str]:
        chunk = self.chunks[chunk_id]
        if not chunk.get("section") or chunk["section"] == self.interpretation_section:
            return []
        return self.definitions.get((chunk["doc_id"], chunk["section"]), [])

    def _reverse(self, chunk_id: str) -> list[str]:
        targets = self.chunks[chunk_id].get("amends") or []
        return sorted((t for t in targets if t in self.order), key=self.order.__getitem__)

    def expand(self, retrieved: list[str], allowed: set[str] | None = None) -> Expansion:
        present = set(retrieved)
        result = Expansion()
        refused: set[str] = set()

        def offer(candidate: str, because: str, trigger: str) -> bool:
            """Add if new and allowed; True if it was added."""
            if candidate in present or candidate in refused or candidate not in self.chunks:
                return False
            if allowed is not None and self.chunks[candidate]["jurisdiction"] not in allowed:
                return False
            if len(retrieved) + len(result.added) >= self.max_chunks:
                refused.add(candidate)
                result.dropped += 1
                return False
            present.add(candidate)
            result.added.append(Added(candidate, because, trigger))
            return True

        for trigger in retrieved:
            for candidate in self._forward(trigger):
                offer(candidate, "amendment_of", trigger)
        for trigger in retrieved:
            for candidate in self._definitions(trigger):
                offer(candidate, "definition_for", trigger)
        for trigger in retrieved:
            taken = 0
            for candidate in self._reverse(trigger):
                if taken == self.reverse_cap:
                    break
                if candidate in present or candidate in refused:
                    continue
                offer(candidate, "amended_by", trigger)
                taken += 1  # a chunk dropped by the total cap still uses its slot
        return result
