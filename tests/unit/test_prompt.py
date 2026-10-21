"""Tests for src/generation/prompt.py."""
import pytest

from src.generation.prompt import INSUFFICIENT, PROMPT, PROMPT_VERSION, build_prompt
from src.retrieval.schema import RetrievalResult, RetrievedChunk

EA, SWK, MY = "Peninsular Malaysia and Labuan", "Sarawak", "Malaysia"

NOTES = {"sarawak": [{"source": "sarawak_amendment_act_2025", "note": "Act A1754 section 2 substituted worker with employee."}]}


def _chunk(chunk_id, jurisdiction=EA, status="in_force", **fields):
    defaults = {
        "chunk_id": chunk_id, "citation": f"{chunk_id} citation", "statute": "Statute", "section_title": f"{chunk_id} title",
        "chunk_type": "provision", "jurisdiction": jurisdiction, "status": status, "content": f"{chunk_id} text",
        "added_because": "retrieved",
    }
    defaults.update(fields)
    return RetrievedChunk(**defaults)


def _result(chunks, region="peninsular", abstained=False, multiple=False):
    return RetrievalResult(
        query="How many days of annual leave?", region=region, mode="hybrid_rerank", gate_enabled=True,
        jurisdictions_searched=None, jurisdictions_found=sorted({c.jurisdiction for c in chunks}),
        multiple_jurisdictions=multiple, abstained=abstained, abstain_reason="low_score" if abstained else None,
        detected_language="english", gate_score=0.9, threshold=0.0325, statutes_held=["Employment Act 1955"],
        chunks=chunks, expansions_dropped=0, index_version="459843bf28ba",
    )


def _render(prompt):
    system, user = PROMPT.format_messages(**prompt.variables)
    return system.content, user.content


def test_prompt_version_and_sentinel():
    assert PROMPT_VERSION == "m4-v1"
    assert INSUFFICIENT == "INSUFFICIENT_CONTEXT"


def test_blocks_follow_result_order():
    chunks = [_chunk("EA1955_s60E_1"), _chunk("IRA1967_s20_1", MY), _chunk("EA1955_s2_def_wages", added_because="definition_for",
                                                                            linked_from="EA1955_s60E_1")]
    prompt = build_prompt(_result(chunks), NOTES)
    assert [b.chunk_id for b in prompt.blocks] == ["EA1955_s60E_1", "IRA1967_s20_1", "EA1955_s2_def_wages"]
    _, user = _render(prompt)
    assert user.index("[1] EA1955_s60E_1") < user.index("[2] IRA1967_s20_1") < user.index("[3] EA1955_s2_def_wages")


def test_header_built_from_metadata_only():
    chunk = _chunk("EA1955_s60E_1", citation="Employment Act 1955, s. 60E(1)", section_title="Annual leave",
                   content="An employee shall be entitled to paid annual leave of eight days.")
    _, user = _render(build_prompt(_result([chunk]), NOTES))
    assert "[1] Employment Act 1955, s. 60E(1) | Annual leave | Peninsular Malaysia and Labuan | in force\n" \
           "An employee shall be entitled to paid annual leave of eight days." in user


def test_header_without_section_title():
    _, user = _render(build_prompt(_result([_chunk("X_1", section_title=None)]), NOTES))
    assert "[1] X_1 citation | Peninsular Malaysia and Labuan | in force\n" in user


def test_superseded_points_to_amending_block():
    chunks = [_chunk("SWK76_s84_1", SWK, "superseded", amended_by=["A1754_s24"]),
              _chunk("A1754_s24", SWK, added_because="amendment_of", linked_from="SWK76_s84_1")]
    _, user = _render(build_prompt(_result(chunks, "sarawak"), NOTES))
    assert "| Sarawak | SUPERSEDED, amended by A1754_s24 (see block 2)\n" in user


def test_superseded_without_amending_chunk_says_not_shown():
    chunks = [_chunk("SWK76_s84_1", SWK, "superseded", amended_by=["A1754_s24"])]
    _, user = _render(build_prompt(_result(chunks, "sarawak"), NOTES))
    assert "| Sarawak | SUPERSEDED, amended by A1754_s24 (amending text not shown)\n" in user


@pytest.mark.parametrize("status, label", [
    ("deleted", "DELETED"), ("omitted", "OMITTED"), ("not_yet_in_force", "NOT YET IN FORCE"), ("in_force", "in force"),
])
def test_status_labels(status, label):
    _, user = _render(build_prompt(_result([_chunk("X_1", status=status)]), NOTES))
    assert f"| Peninsular Malaysia and Labuan | {label}\n" in user


def test_sarawak_note_only_when_sarawak_chunk():
    note = "Act A1754 section 2 substituted worker with employee."
    with_swk = build_prompt(_result([_chunk("SWK76_s8_1", SWK)], "sarawak"), NOTES)
    without = build_prompt(_result([_chunk("EA1955_s60E_1")]), NOTES)
    assert with_swk.notes == [note] and note in _render(with_swk)[1]
    assert without.notes == [] and note not in _render(without)[1]


def test_in_force_notes_included_verbatim():
    footnote = "*NOTE: section 12A not yet in force."
    _, user = _render(build_prompt(_result([_chunk("IRA1967_s12A", MY, in_force_notes=[footnote])]), NOTES))
    assert footnote in user


def test_region_line():
    assert "User's region: Sabah" in _render(build_prompt(_result([_chunk("X_1")], "sabah"), NOTES))[1]
    assert "User's region: not given" in _render(build_prompt(_result([_chunk("X_1")], None), NOTES))[1]


def test_question_is_last():
    _, user = _render(build_prompt(_result([_chunk("X_1")]), NOTES))
    assert user.rstrip().endswith("Question: How many days of annual leave?")


def test_rules_forbid_advice_and_section_names():
    system, _ = _render(build_prompt(_result([_chunk("X_1")]), NOTES))
    assert "Do not name Acts, Ordinances or section numbers yourself." in system
    assert "Do not tell the user what they should do, and do not give legal advice." in system
    assert "reply exactly INSUFFICIENT_CONTEXT" in system


def test_braces_in_content_do_not_break_the_template():
    _, user = _render(build_prompt(_result([_chunk("X_1", content="rate = {monthly rate of pay} / 26")]), NOTES))
    assert "rate = {monthly rate of pay} / 26" in user


def test_abstained_result_raises():
    with pytest.raises(ValueError):
        build_prompt(_result([], abstained=True), NOTES)
