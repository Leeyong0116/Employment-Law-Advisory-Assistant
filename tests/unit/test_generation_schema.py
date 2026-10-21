"""Tests for src/generation/schema.py."""
import pytest
from pydantic import ValidationError

from src.generation.schema import Abstention, AnswerChecks, Citation, GeneratedAnswer, GeneratorInfo
from src.retrieval.schema import RetrievedChunk


def _chunk(chunk_id="EA1955_s60E_1", **fields):
    return RetrievedChunk(**{
        "chunk_id": chunk_id, "citation": "Employment Act 1955, s. 60E(1)", "statute": "Employment Act 1955",
        "act_number": "Act 265", "section": "60E", "subsection": "(1)", "section_title": "Annual leave",
        "chunk_type": "provision", "jurisdiction": "Peninsular Malaysia and Labuan", "status": "in_force",
        "content": "An employee shall be entitled to paid annual leave ...", "source_page": 58,
        "source_url": "https://lom.agc.gov.my/", "source_version": "as at 1 January 2023",
        "added_because": "retrieved", **fields,
    })


def _cit(number, chunk_id="EA1955_s60E_1"):
    return Citation.from_chunk(number, _chunk(chunk_id))


def _base(**overrides):
    fields = dict(
        query="How many days of annual leave?", region="peninsular", status="answered",
        answer="Eight days a year for under two years of service [1].", citations=[_cit(1)], abstention=None,
        notes=[], external_dependencies=[], checks=AnswerChecks(),
        generator=GeneratorInfo(model="Qwen/Qwen3-14B-AWQ", temperature=0, seed=0, prompt_version="m4-v1"),
        context_chunk_ids=["EA1955_s60E_1"], index_version="459843bf28ba",
    )
    fields.update(overrides)
    return fields


def test_citation_copies_metadata_exactly():
    c = Citation.from_chunk(1, _chunk())
    assert (c.number, c.chunk_id, c.citation, c.source_page) == (1, "EA1955_s60E_1", "Employment Act 1955, s. 60E(1)", 58)
    assert (c.statute, c.act_number, c.section, c.subsection, c.section_title) == (
        "Employment Act 1955", "Act 265", "60E", "(1)", "Annual leave")
    assert (c.jurisdiction, c.status, c.source_url, c.source_version) == (
        "Peninsular Malaysia and Labuan", "in_force", "https://lom.agc.gov.my/", "as at 1 January 2023")


def test_valid_answer_builds():
    assert GeneratedAnswer(**_base()).status == "answered"


def test_answered_needs_answer():
    with pytest.raises(ValidationError):
        GeneratedAnswer(**_base(status="answered", answer=None))


def test_abstained_needs_notice():
    with pytest.raises(ValidationError):
        GeneratedAnswer(**_base(status="abstained", answer=None, citations=[], abstention=None))


def test_abstained_has_no_answer_or_citations():
    notice = Abstention(reason="low_score", statutes_held=["Employment Act 1955 (Act 265)"], message="Outside scope.")
    with pytest.raises(ValidationError):
        GeneratedAnswer(**_base(status="abstained", abstention=notice))
    ok = GeneratedAnswer(**_base(status="abstained", answer=None, citations=[], abstention=notice, generator=None))
    assert ok.abstention.reason == "low_score"


def test_citation_numbers_are_1_to_n_in_order():
    with pytest.raises(ValidationError):
        GeneratedAnswer(**_base(citations=[_cit(2), _cit(1, "EA1955_s60E_2")]))
    with pytest.raises(ValidationError):
        GeneratedAnswer(**_base(citations=[_cit(1), _cit(3, "EA1955_s60E_2")]))
