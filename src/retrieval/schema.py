"""Typed output of the retrieval pipeline.

Generation (M4) and the API (M5) consume these models and nothing else.
Every citation the system shows is built from these fields, which are
copied from chunk metadata, never from generated text (CLAUDE.md, core
contribution 1).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator

Mode = Literal["dense", "hybrid", "hybrid_rerank"]
AbstainReason = Literal["language", "low_score", "no_candidates"]
# How a chunk got into the result, read as "<added_because> <linked_from>":
#   retrieved       ranked by the retrieval method itself
#   amendment_of    an A1754 chunk that amends linked_from (Sarawak)
#   amended_by      principal text amended by linked_from, an A1754 chunk
#   definition_for  a definition in the same section as linked_from
AddedBecause = Literal["retrieved", "amendment_of", "amended_by", "definition_for"]

_LIST_FIELDS = ("amended_by", "amends", "in_force_notes", "cross_references_external")


class RetrievedChunk(BaseModel):
    chunk_id: str
    citation: str
    statute: str
    act_number: str | None = None
    section: str | None = None
    subsection: str | None = None
    section_title: str | None = None
    chunk_type: str
    jurisdiction: str
    status: str
    content: str
    source_page: int | None = None
    source_url: str | None = None
    source_version: str | None = None
    amended_by: list[str] = []
    amends: list[str] = []
    in_force_notes: list[str] = []
    cross_references_external: list[str] = []
    # The mode's own score (cosine, RRF or reranker) and rank; null for
    # chunks added by expansion, which were not ranked.
    score: float | None = None
    rank: int | None = None
    added_because: AddedBecause
    linked_from: str | None = None

    @field_validator(*_LIST_FIELDS, mode="before")
    @classmethod
    def _none_is_empty(cls, value):
        return [] if value is None else value

    @classmethod
    def from_chunk(cls, chunk: dict, **retrieval_fields) -> "RetrievedChunk":
        known = {name: chunk[name] for name in cls.model_fields if name in chunk and name not in retrieval_fields}
        return cls(**known, **retrieval_fields)


class RetrievalResult(BaseModel):
    query: str
    region: str | None
    mode: Mode
    gate_enabled: bool
    jurisdictions_searched: list[str] | None  # null: no region, all searched
    jurisdictions_found: list[str]
    # True when no region was given and the chunks come from more than one
    # territory. "Malaysia" (the IRA) applies everywhere and does not count.
    multiple_jurisdictions: bool
    abstained: bool
    abstain_reason: AbstainReason | None
    detected_language: str | None
    gate_score: float | None
    threshold: float | None
    statutes_held: list[str]
    chunks: list[RetrievedChunk]
    expansions_dropped: int
    index_version: str
