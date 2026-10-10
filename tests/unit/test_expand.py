"""Tests for src/retrieval/expand.py: amendment links and same-section definitions."""
from src.retrieval.expand import Expander

SWK, EA = "Sarawak", "Peninsular Malaysia and Labuan"


def _c(chunk_id, doc, section, jurisdiction, chunk_type="provision", amended_by=None, amends=None):
    return chunk_id, {"chunk_id": chunk_id, "doc_id": doc, "section": section, "jurisdiction": jurisdiction,
                      "chunk_type": chunk_type, "amended_by": amended_by, "amends": amends}


# Insertion order is document order, as in chunks.jsonl.
CHUNKS = dict([
    _c("E2_def", "ea", "2", EA, "definition"),
    _c("E2_2", "ea", "2", EA),
    _c("E37_1_def_a", "ea", "37", EA, "definition"),
    _c("E37_2", "ea", "37", EA),
    _c("E37_3_def_b", "ea", "37", EA, "definition"),
    _c("S2_def", "swk", "2", SWK, "definition"),
    _c("S84_1", "swk", "84", SWK, amended_by=["A24"]),
    _c("S84_2", "swk", "84", SWK, amended_by=["A24"]),
    _c("S84_3", "swk", "84", SWK, amended_by=["A24"]),
    _c("S84_4", "swk", "84", SWK, amended_by=["A24"]),
    _c("A24", "a1754", "24", SWK, "amendment", amends=["S84_4", "S84_3", "S84_2", "S84_1"]),
])


def _expand(retrieved, allowed=None, max_chunks=12, reverse_cap=3):
    expansion = Expander(CHUNKS, max_chunks=max_chunks, reverse_cap=reverse_cap).expand(retrieved, allowed)
    return [(a.chunk_id, a.added_because, a.linked_from) for a in expansion.added], expansion.dropped


def test_nothing_retrieved_nothing_added():
    assert _expand([]) == ([], 0)


def test_superseded_chunk_brings_its_amendment():
    assert _expand(["S84_1"])[0] == [("A24", "amendment_of", "S84_1")]


def test_a_chunk_is_added_once_and_credited_to_the_first_trigger():
    added, _ = _expand(["S84_2", "S84_1"])
    assert [a for a in added if a[0] == "A24"] == [("A24", "amendment_of", "S84_2")]


def test_retrieved_chunks_are_never_added_again():
    added, _ = _expand(["A24", "S84_1"])
    assert "A24" not in [a[0] for a in added] and "S84_1" not in [a[0] for a in added]


def test_amending_chunk_brings_amended_text_in_document_order_capped():
    added, _ = _expand(["A24"], reverse_cap=3)
    assert added == [("S84_1", "amended_by", "A24"), ("S84_2", "amended_by", "A24"), ("S84_3", "amended_by", "A24")]


def test_reverse_cap_counts_only_chunks_not_already_present():
    added, _ = _expand(["A24", "S84_1"], reverse_cap=3)
    assert [a[0] for a in added if a[1] == "amended_by"] == ["S84_2", "S84_3", "S84_4"]


def test_same_section_definitions_are_added_in_document_order():
    added, _ = _expand(["E37_2"])
    assert added == [("E37_1_def_a", "definition_for", "E37_2"), ("E37_3_def_b", "definition_for", "E37_2")]


def test_a_retrieved_definition_brings_its_siblings_not_itself():
    added, _ = _expand(["E37_3_def_b"])
    assert added == [("E37_1_def_a", "definition_for", "E37_3_def_b")]


def test_interpretation_section_definitions_are_not_co_retrieved():
    assert _expand(["E2_2"])[0] == []
    assert _expand(["E2_def"])[0] == []


def test_cap_keeps_forward_links_first_and_counts_what_was_dropped():
    # 2 retrieved + cap 3 leaves one slot: the amendment wins over definitions.
    added, dropped = _expand(["E37_2", "S84_1"], max_chunks=3)
    assert added == [("A24", "amendment_of", "S84_1")]
    assert dropped == 2


def test_definitions_come_before_reverse_links_under_the_cap():
    added, dropped = _expand(["E37_2", "A24"], max_chunks=4)
    assert added == [("E37_1_def_a", "definition_for", "E37_2"), ("E37_3_def_b", "definition_for", "E37_2")]
    assert dropped == 3


def test_expansion_never_leaves_the_allowed_jurisdictions():
    added, _ = _expand(["S84_1", "E37_2"], allowed={EA, "Malaysia"})
    assert all(CHUNKS[a[0]]["jurisdiction"] in {EA, "Malaysia"} for a in added)
    assert "A24" not in [a[0] for a in added]
