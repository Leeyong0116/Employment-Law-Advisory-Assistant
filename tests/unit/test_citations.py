"""Tests for src/generation/citations.py."""
import pytest

from src.generation.citations import resolve
from src.retrieval.schema import RetrievedChunk


def _blocks(n):
    return [RetrievedChunk(chunk_id=f"C{i}", citation=f"Act, s. {i}", statute="Act", chunk_type="provision",
                           jurisdiction="Sabah", status="in_force", content="text", source_page=i,
                           added_because="retrieved") for i in range(1, n + 1)]


def test_renumbers_by_first_use():
    blocks = _blocks(3)
    r = resolve("Leave is eight days [3]. Sick leave is fourteen days [1].", blocks)
    assert r.answer == "Leave is eight days [1]. Sick leave is fourteen days [2]."
    assert [(c.number, c.chunk_id) for c in r.citations] == [(1, "C3"), (2, "C1")]


def test_citations_copy_block_metadata():
    r = resolve("Leave is eight days [2].", _blocks(2))
    assert (r.citations[0].citation, r.citations[0].source_page) == ("Act, s. 2", 2)


def test_repeated_marker_keeps_its_number():
    r = resolve("A rule here [2]. Another rule here [3]. Back to the first [2].", _blocks(3))
    assert r.answer == "A rule here [1]. Another rule here [2]. Back to the first [1]."
    assert len(r.citations) == 2


@pytest.mark.parametrize("text, expected", [
    ("Rule [1, 3].", "Rule [1][2]."),
    ("Rule [1][3].", "Rule [1][2]."),
    ("Rule [1-3].", "Rule [1][2][3]."),
    ("Rule [ 2 ].", "Rule [1]."),
])
def test_group_and_range_forms(text, expected):
    assert resolve(text, _blocks(5)).answer == expected


def test_out_of_range_dropped_and_recorded():
    r = resolve("X is the rule [9].", _blocks(5))
    assert r.answer == "X is the rule."
    assert r.invalid_markers == [9] and r.citations == []


def test_partly_invalid_group_keeps_valid_numbers():
    r = resolve("X is the rule [2, 9].", _blocks(5))
    assert r.answer == "X is the rule [1]."
    assert r.invalid_markers == [9]


def test_zero_is_invalid():
    assert resolve("X is the rule [0].", _blocks(2)).invalid_markers == [0]


def test_uncited_sentences_counted():
    r = resolve("The rule is long and has no marker at all. Leave is eight days [1].", _blocks(1))
    assert r.uncited_sentences == 1


def test_marker_after_full_stop_counts_for_its_sentence():
    r = resolve("Leave is eight days for new employees. [1] Sick leave is fourteen days a year [1].", _blocks(1))
    assert r.uncited_sentences == 0


def test_short_lines_and_headings_not_counted():
    r = resolve("In Sabah:\n- Eight days a year [1].\nIn short, yes.", _blocks(1))
    assert r.uncited_sentences == 0


@pytest.mark.parametrize("text, mention", [
    ("Under section 60E you get eight days [1].", "section 60E"),
    ("As s. 60E(1) says, eight days [1].", "s. 60E(1)"),
    ("The Employment Act 1955 gives eight days [1].", "Employment Act 1955"),
    ("Under reg. 6 the rate is ten days [1].", "reg. 6"),
])
def test_provision_mentions_flagged(text, mention):
    assert resolve(text, _blocks(1)).provision_mentions == [mention]


def test_no_mentions_in_clean_answer():
    assert resolve("You get eight days of paid leave a year [1].", _blocks(1)).provision_mentions == []


def test_unused_blocks_are_not_cited():
    r = resolve("Leave is eight days [2].", _blocks(5))
    assert [c.chunk_id for c in r.citations] == ["C2"]
