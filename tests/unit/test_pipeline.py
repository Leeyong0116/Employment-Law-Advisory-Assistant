"""Tests for src/retrieval/pipeline.py, with fake components (no GPU, no database)."""
import pytest

from src.retrieval.language import LanguageCheck
from src.retrieval.pipeline import Retriever

EA, SBH, SWK, MY = "Peninsular Malaysia and Labuan", "Sabah", "Sarawak", "Malaysia"


def _c(chunk_id, jurisdiction, section="1", parse_rule="subsection", amended_by=None, chunk_type="provision"):
    return chunk_id, {
        "chunk_id": chunk_id, "doc_id": chunk_id.split("_")[0], "citation": f"{chunk_id} citation",
        "statute": chunk_id.split("_")[0], "section": section, "chunk_type": chunk_type,
        "jurisdiction": jurisdiction, "status": "in_force", "content": f"{chunk_id} text",
        "parse_rule": parse_rule, "amended_by": amended_by, "amends": None,
    }


CHUNKS = dict([
    _c("EA_s60E_1", EA, "60E"),
    _c("EA_s37_2", EA, "37"),
    _c("EA_s92", EA, "92", parse_rule="placeholder"),
    _c("SBH_s83_1", SBH, "83"),
    _c("SWK_s84_1", SWK, "84", amended_by=["A1754_s24"]),
    _c("A1754_s24", SWK, "24", chunk_type="amendment"),
    _c("IRA_s5_1", MY, "5"),
])

CONFIG = {
    "corpus": {"documents": [
        {"short_name": "Employment Act 1955", "act_number": "Act 265", "jurisdiction_label": EA},
        {"short_name": "Industrial Relations Act 1967", "act_number": "Act 177", "jurisdiction_label": MY},
    ]},
    "retrieval": {
        "regions": {"peninsular": [EA, MY], "sabah": [SBH, MY], "sarawak": [SWK, MY]},
        "top_k_dense": 20, "top_k_sparse": 20, "rerank_pool": 20, "top_k_final": 2, "max_chunks": 12,
        "reverse_amendment_cap": 3, "exclude_placeholders_from_dense": True,
        "abstention_threshold": {"dense": 0.5, "hybrid": 0.5, "hybrid_rerank": 0.3},
    },
}

# Per-query fake scores: dense cosine, BM25, reranker.
DENSE = {"EA_s60E_1": 0.70, "SBH_s83_1": 0.66, "SWK_s84_1": 0.65, "IRA_s5_1": 0.60, "EA_s92": 0.80, "EA_s37_2": 0.4}
BM25 = {"IRA_s5_1": 9.0, "EA_s92": 5.0, "EA_s60E_1": 3.0}
RERANK = {"EA_s60E_1": 0.95, "SBH_s83_1": 0.2, "SWK_s84_1": 0.9, "IRA_s5_1": 0.5, "EA_s92": 0.1}


class FakeEmbedder:
    def encode(self, texts):
        return [[1.0, 0.0]] * len(texts), [{}] * len(texts)


class FakeStore:
    def __init__(self, scores):
        self.scores, self.calls = scores, []

    def dense_search(self, vector, k=20, jurisdictions=None, index_version=None, exclude_parse_rules=None):
        self.calls.append(exclude_parse_rules)
        hits = [(c, s) for c, s in self.scores.items()
                if (jurisdictions is None or CHUNKS[c]["jurisdiction"] in jurisdictions)
                and not (exclude_parse_rules and CHUNKS[c]["parse_rule"] in exclude_parse_rules)]
        return sorted(hits, key=lambda h: (-h[1], h[0]))[:k]

    def similarities(self, vector, chunk_ids, index_version=None):
        return {c: self.scores.get(c, 0.0) for c in chunk_ids}


class FakeBm25:
    def __init__(self, scores):
        self.scores = scores

    def search(self, query, k=20, jurisdictions=None):
        hits = [(c, s) for c, s in self.scores.items()
                if jurisdictions is None or CHUNKS[c]["jurisdiction"] in jurisdictions]
        return sorted(hits, key=lambda h: (-h[1], h[0]))[:k]


class FakeReranker:
    def __init__(self, scores):
        self.scores = scores

    def rerank(self, query, chunk_ids, chunks):
        return sorted(((c, self.scores.get(c, 0.0)) for c in chunk_ids), key=lambda h: (-h[1], h[0]))


class FakeLanguage:
    def __init__(self, passed=True, language="en"):
        self.result = LanguageCheck(passed, language)

    def check(self, query):
        return self.result


def _retriever(dense=DENSE, bm25=BM25, rerank=RERANK, language=None, config=CONFIG):
    return Retriever(config, CHUNKS, FakeEmbedder(), FakeStore(dense), FakeBm25(bm25), FakeReranker(rerank),
                     language or FakeLanguage(), index_version="v1")


def _ids(result, because="retrieved"):
    return [c.chunk_id for c in result.chunks if c.added_because == because]


class TestModes:
    def test_dense_ranks_by_cosine_and_gates_on_the_top_cosine(self):
        result = _retriever().retrieve("q", "peninsular", mode="dense")
        assert _ids(result) == ["EA_s60E_1", "IRA_s5_1"]
        assert result.gate_score == pytest.approx(0.70)

    def test_hybrid_fuses_and_gates_on_the_best_cosine_among_its_top_k(self):
        result = _retriever().retrieve("q", "peninsular", mode="hybrid")
        # EA_s60E_1: dense 1 + BM25 3; IRA_s5_1: dense 2 + BM25 1; EA_s92 is BM25 only (placeholder)
        assert _ids(result) == ["IRA_s5_1", "EA_s60E_1"]
        assert result.gate_score == pytest.approx(0.70)

    def test_hybrid_rerank_orders_by_reranker_and_gates_on_its_top_score(self):
        result = _retriever().retrieve("q", "peninsular", mode="hybrid_rerank")
        assert _ids(result) == ["EA_s60E_1", "IRA_s5_1"]
        assert result.gate_score == pytest.approx(0.95)
        assert result.chunks[0].score == pytest.approx(0.95) and result.chunks[0].rank == 1

    def test_unknown_mode_or_region_is_an_error(self):
        with pytest.raises(ValueError):
            _retriever().retrieve("q", None, mode="agentic")
        with pytest.raises(ValueError):
            _retriever().retrieve("q", "johor")


class TestFilters:
    def test_placeholders_are_excluded_from_dense(self):
        r = _retriever()
        result = r.retrieve("q", "peninsular", mode="dense")
        assert r.store.calls[-1] == ["placeholder", "range_placeholder"]
        assert "EA_s92" not in [c.chunk_id for c in result.chunks]  # highest cosine, but a placeholder

    def test_bm25_still_finds_placeholders_by_section_number(self):
        config = {**CONFIG, "retrieval": {**CONFIG["retrieval"], "top_k_final": 4}}
        result = _retriever(config=config).retrieve("section 92", "peninsular", mode="hybrid")
        assert "EA_s92" in _ids(result)

    def test_region_keeps_other_territories_out(self):
        result = _retriever().retrieve("q", "sabah", mode="hybrid_rerank")
        assert {c.jurisdiction for c in result.chunks} <= {SBH, MY}
        assert result.jurisdictions_searched == [SBH, MY]


class TestGate:
    def test_low_top_score_abstains_with_no_chunks(self):
        result = _retriever(rerank={c: 0.01 for c in RERANK}).retrieve("dog", None)
        assert result.abstained and result.abstain_reason == "low_score"
        assert result.chunks == [] and result.gate_score == pytest.approx(0.01)
        assert result.statutes_held == ["Employment Act 1955 (Act 265), Peninsular Malaysia and Labuan",
                                        "Industrial Relations Act 1967 (Act 177), Malaysia"]

    def test_score_equal_to_the_threshold_passes(self):
        result = _retriever(rerank={"EA_s60E_1": 0.3}).retrieve("q", "peninsular")
        assert not result.abstained

    def test_gate_off_never_abstains_on_score(self):
        result = _retriever(rerank={c: 0.01 for c in RERANK}).retrieve("dog", None, gate=False)
        assert not result.abstained and result.chunks and result.gate_enabled is False

    def test_no_threshold_configured_means_no_score_gate(self):
        config = {**CONFIG, "retrieval": {**CONFIG["retrieval"], "abstention_threshold": None}}
        result = _retriever(rerank={c: 0.01 for c in RERANK}, config=config).retrieve("dog", None)
        assert not result.abstained and result.threshold is None

    def test_non_english_abstains_before_retrieval(self):
        r = _retriever(language=FakeLanguage(False, "ms"))
        result = r.retrieve("cuti bersalin berapa hari", "sabah")
        assert result.abstained and result.abstain_reason == "language"
        assert result.detected_language == "ms" and r.store.calls == []

    def test_nothing_found_abstains(self):
        result = _retriever(dense={}, bm25={}).retrieve("q", None)
        assert result.abstained and result.abstain_reason == "no_candidates"


class TestExpansionAndJurisdictions:
    def test_superseded_chunk_brings_its_amendment(self):
        result = _retriever().retrieve("maternity", "sarawak")
        assert "SWK_s84_1" in _ids(result)
        amendment = [c for c in result.chunks if c.added_because == "amendment_of"]
        assert [(c.chunk_id, c.linked_from, c.rank, c.score) for c in amendment] == [
            ("A1754_s24", "SWK_s84_1", None, None)]

    def test_no_region_and_several_territories_is_flagged(self):
        result = _retriever(rerank={"SBH_s83_1": 0.9, "SWK_s84_1": 0.8}).retrieve("maternity", None)
        assert result.multiple_jurisdictions
        assert set(result.jurisdictions_found) == {SBH, SWK}

    def test_one_territory_plus_ira_is_not_flagged(self):
        only_ea = _retriever(rerank={"EA_s60E_1": 0.9, "IRA_s5_1": 0.8}).retrieve("q", None)
        assert {c.jurisdiction for c in only_ea.chunks} == {EA, MY}
        assert not only_ea.multiple_jurisdictions

    def test_a_region_never_sets_the_flag(self):
        result = _retriever().retrieve("q", "sarawak")
        assert not result.multiple_jurisdictions

    def test_total_chunks_never_exceed_the_cap(self):
        config = {**CONFIG, "retrieval": {**CONFIG["retrieval"], "max_chunks": 2}}
        result = _retriever(config=config).retrieve("maternity", "sarawak")
        assert len(result.chunks) <= 2
        assert result.expansions_dropped == 1
