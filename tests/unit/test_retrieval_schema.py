"""Tests for src/retrieval/schema.py."""
import pytest
from pydantic import ValidationError

from src.retrieval.schema import RetrievalResult, RetrievedChunk

CHUNK = {
    "chunk_id": "SWK76_s84_1", "citation": "Labour Ordinance (Sarawak), s. 84(1)",
    "statute": "Labour Ordinance (Sarawak)", "act_number": "Sarawak Cap. 76", "section": "84",
    "subsection": "(1)", "section_title": "Maternity leave", "chunk_type": "provision",
    "jurisdiction": "Sarawak", "status": "superseded", "content": "Every female worker ...",
    "source_page": 61, "source_url": None, "source_version": "incorporating amendments up to 31 July 2006",
    "amended_by": ["A1754_s24"], "amends": None, "in_force_notes": None, "cross_references_external": [],
    "parse_rule": "subsection",  # extra chunk fields are ignored
}


def test_built_from_a_chunk_with_retrieval_fields():
    item = RetrievedChunk.from_chunk(CHUNK, score=0.97, rank=1, added_because="retrieved")
    assert item.citation == "Labour Ordinance (Sarawak), s. 84(1)"
    assert item.amended_by == ["A1754_s24"]
    assert item.score == 0.97 and item.rank == 1 and item.linked_from is None


def test_null_lists_in_the_chunk_become_empty_lists():
    item = RetrievedChunk.from_chunk(CHUNK, added_because="retrieved")
    assert item.amends == [] and item.in_force_notes == []


def test_expansion_chunk_has_no_rank_and_names_its_trigger():
    item = RetrievedChunk.from_chunk(CHUNK, added_because="amended_by", linked_from="A1754_s24")
    assert item.rank is None and item.score is None and item.linked_from == "A1754_s24"


def test_unknown_reason_is_rejected():
    with pytest.raises(ValidationError):
        RetrievedChunk.from_chunk(CHUNK, added_because="because")


def test_result_round_trips_through_json():
    result = RetrievalResult(
        query="maternity leave", region="sarawak", mode="hybrid_rerank", gate_enabled=True,
        jurisdictions_searched=["Sarawak", "Malaysia"], jurisdictions_found=["Sarawak"],
        multiple_jurisdictions=False, abstained=False, abstain_reason=None, detected_language="en",
        gate_score=0.97, threshold=0.1, statutes_held=["Employment Act 1955 (Act 265)"],
        chunks=[RetrievedChunk.from_chunk(CHUNK, score=0.97, rank=1, added_because="retrieved")],
        expansions_dropped=0, index_version="abc123",
    )
    assert RetrievalResult.model_validate_json(result.model_dump_json()) == result


def test_unknown_mode_is_rejected():
    with pytest.raises(ValidationError):
        RetrievalResult(
            query="q", region=None, mode="agentic", gate_enabled=True, jurisdictions_searched=None,
            jurisdictions_found=[], multiple_jurisdictions=False, abstained=True,
            abstain_reason="no_candidates", detected_language=None, gate_score=None, threshold=None,
            statutes_held=[], chunks=[], expansions_dropped=0, index_version="v",
        )
