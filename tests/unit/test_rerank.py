"""Tests for src/retrieval/rerank.py, with a fake cross-encoder and tokenizer."""
from src.retrieval import rerank


class FakeTokenizer:
    """One token per word, so window arithmetic is easy to follow."""

    def encode(self, text, add_special_tokens=False):
        return text.split()

    def decode(self, ids):
        return " ".join(ids)


class FakeModel:
    """Scores a pair by how many query words appear in the passage."""

    def __init__(self):
        self.tokenizer = FakeTokenizer()
        self.calls = []

    def compute_score(self, pairs, normalize=True, max_length=512):
        self.calls.append(pairs)
        return [sum(word in passage.split() for word in query.split()) / 10 for query, passage in pairs]


def _reranker(max_length=512):
    r = rerank.Reranker("fake", max_length=max_length, safety_margin=0)
    r._model = FakeModel()
    return r


def _chunk(content, citation="Act, s. 1", title=None):
    return {"citation": citation, "section_title": title, "content": content}


CHUNKS = {
    "A": _chunk("annual leave of eight days"),
    "B": _chunk("maternity leave of ninety-eight days"),
    "C": _chunk("rest day"),
}


def test_candidates_are_reordered_by_the_cross_encoder():
    ranked = _reranker().rerank("maternity leave days", ["A", "B", "C"], CHUNKS)
    assert [chunk_id for chunk_id, _ in ranked] == ["B", "A", "C"]


def test_ties_are_broken_by_chunk_id():
    ranked = _reranker().rerank("nothing matches", ["C", "A", "B"], CHUNKS)
    assert [chunk_id for chunk_id, _ in ranked] == ["A", "B", "C"]


def test_no_candidates():
    assert _reranker().rerank("anything", [], CHUNKS) == []


class TestPassage:
    def test_citation_and_title_come_before_the_content(self):
        chunk = _chunk("Every employee shall ...", "Employment Act 1955, s. 60E(1)", "Annual leave")
        assert rerank.passage(chunk) == "Employment Act 1955, s. 60E(1) Annual leave Every employee shall ..."

    def test_missing_title_is_skipped(self):
        assert rerank.passage(_chunk("text", "Act, s. 2")) == "Act, s. 2 text"

    def test_section_number_query_can_match_the_citation(self):
        chunks = {"X": _chunk("(Deleted by Act A1026).", "Employment Act 1955, s. 92"),
                  "Y": _chunk("wages shall be paid", "Employment Act 1955, s. 19")}
        ranked = _reranker().rerank("s. 92", ["Y", "X"], chunks)
        assert ranked[0][0] == "X"


class TestSlidingWindow:
    # max_length 20 - 4 special tokens - 1 query word - 2 header words = 13 content words per window
    def _long(self, words):
        return _chunk(" ".join(words), "Act s.9")

    def test_short_chunk_is_one_window(self):
        r = _reranker(max_length=20)
        assert r.windows("q", self._long(["w"] * 5)) == ["Act s.9 " + " ".join(["w"] * 5)]

    def test_long_chunk_is_split_and_every_window_keeps_the_header(self):
        r = _reranker(max_length=20)
        windows = r.windows("q", self._long([f"w{i}" for i in range(40)]))
        assert len(windows) > 1
        assert all(w.startswith("Act s.9 ") for w in windows)

    def test_windows_cover_the_whole_chunk_including_the_end(self):
        r = _reranker(max_length=20)
        words = [f"w{i}" for i in range(40)]
        covered = {word for w in r.windows("q", self._long(words)) for word in w.split()[2:]}
        assert covered == set(words)

    def test_windows_fit_the_model_limit(self):
        r = _reranker(max_length=20)
        budget = 20 - rerank.SPECIAL_TOKENS - 1  # query is one word
        for w in r.windows("q", self._long([f"w{i}" for i in range(40)])):
            assert len(w.split()) <= budget

    def test_chunk_score_is_its_best_window(self):
        r = _reranker(max_length=20)
        words = [f"w{i}" for i in range(39)] + ["needle"]
        ranked = r.rerank("needle", ["L"], {"L": self._long(words)})
        assert ranked == [("L", 0.1)]

    def test_without_windows_the_tail_would_be_invisible(self):
        """The case the window exists for: the match is only in the last words."""
        r = _reranker(max_length=20)
        words = [f"w{i}" for i in range(39)] + ["needle"]
        first_window = r.windows("needle", self._long(words))[0]
        assert "needle" not in first_window.split()
