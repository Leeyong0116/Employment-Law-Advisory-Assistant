"""Tests for src/retrieval/fusion.py (reciprocal rank fusion)."""
import pytest

from src.retrieval import fusion


def test_a_chunk_ranked_high_in_both_lists_wins():
    dense = [("A", 0.9), ("B", 0.8), ("C", 0.7)]
    bm25 = [("B", 12.0), ("A", 3.0), ("D", 2.0)]
    ranked = fusion.rrf([dense, bm25])
    assert [chunk_id for chunk_id, _ in ranked][:2] in (["A", "B"], ["B", "A"])
    assert {chunk_id for chunk_id, _ in ranked} == {"A", "B", "C", "D"}


def test_scores_use_ranks_not_raw_scores():
    # A BM25 score of 500 must not swamp a cosine similarity of 0.9.
    dense = [("A", 0.9), ("B", 0.1)]
    bm25 = [("B", 500.0), ("A", 499.0)]
    ranked = dict(fusion.rrf([dense, bm25]))
    assert ranked["A"] == pytest.approx(ranked["B"])


def test_the_formula():
    ranked = dict(fusion.rrf([[("A", 1.0)], [("B", 1.0), ("A", 0.5)]], c=60))
    assert ranked["A"] == pytest.approx(1 / 61 + 1 / 62)
    assert ranked["B"] == pytest.approx(1 / 61)


def test_ties_are_broken_by_chunk_id():
    ranked = fusion.rrf([[("B", 1.0)], [("A", 1.0)]])
    assert [chunk_id for chunk_id, _ in ranked] == ["A", "B"]


def test_empty_lists():
    assert fusion.rrf([[], []]) == []
