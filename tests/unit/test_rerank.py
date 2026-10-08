"""Tests for src/retrieval/rerank.py, with a fake cross-encoder."""
from src.retrieval import rerank


class FakeModel:
    """Scores a pair by how many query words appear in the passage."""

    def compute_score(self, pairs, normalize=True):
        return [sum(word in passage for word in query.split()) / 10 for query, passage in pairs]


def _reranker():
    r = rerank.Reranker("fake")
    r._model = FakeModel()
    return r


CHUNKS = {
    "A": {"content": "annual leave of eight days"},
    "B": {"content": "maternity leave of ninety-eight days"},
    "C": {"content": "rest day"},
}


def test_candidates_are_reordered_by_the_cross_encoder():
    ranked = _reranker().rerank("maternity leave days", ["A", "B", "C"], CHUNKS)
    assert [chunk_id for chunk_id, _ in ranked] == ["B", "A", "C"]


def test_ties_are_broken_by_chunk_id():
    ranked = _reranker().rerank("nothing matches", ["C", "A", "B"], CHUNKS)
    assert [chunk_id for chunk_id, _ in ranked] == ["A", "B", "C"]


def test_no_candidates():
    assert _reranker().rerank("anything", [], CHUNKS) == []
