"""Tests for src/indexing/bm25.py."""
from src.indexing import bm25


def _chunk(chunk_id, citation, content, jurisdiction="Peninsular Malaysia and Labuan", title=None):
    return {"chunk_id": chunk_id, "citation": citation, "section_title": title,
            "content": content, "jurisdiction": jurisdiction}


class TestTokenize:
    def test_section_ids_stay_whole(self):
        # "60E" must not become "60" + "e", or "section 60E" matches every
        # chunk that mentions section 60.
        assert "60e" in bm25.tokenize("Employment Act 1955, s. 60E")

    def test_a_subsection_reference_also_yields_its_section(self):
        tokens = bm25.tokenize("s. 2(1)")
        assert "2(1)" in tokens and "2" in tokens

    def test_lettered_subsections(self):
        assert "60i(1a)" in bm25.tokenize("s. 60I(1A)")

    def test_stopwords_and_case(self):
        assert bm25.tokenize("The Employee shall be ALLOWED") == ["employee", "shall", "allowed"]


class TestIndexText:
    def test_citation_and_title_are_searchable_but_content_leads(self):
        text = bm25.index_text(_chunk("EA1955_s60E_1", "Employment Act 1955, s. 60E(1)",
                                      "An employee shall be entitled to paid annual leave", title="Annual leave"))
        assert "60E(1)" in text and "Annual leave" in text and "paid annual leave" in text


class TestSearch:
    CHUNKS = [
        _chunk("EA_60E", "Employment Act 1955, s. 60E(1)", "paid annual leave of eight days", title="Annual leave"),
        _chunk("EA_60D", "Employment Act 1955, s. 60D(1)", "paid holiday at his ordinary rate of pay", title="Holidays"),
        _chunk("SBH_104D", "Labour Ordinance (Sabah), s. 104D(1)", "paid annual leave of eight days",
               jurisdiction="Sabah", title="Annual leave"),
        _chunk("IRA_5", "Industrial Relations Act 1967, s. 5(1)", "no employer shall dismiss a workman for joining a trade union",
               jurisdiction="Malaysia"),
    ]

    def test_finds_by_words(self):
        index = bm25.Bm25Index.build(self.CHUNKS)
        assert index.search("annual leave", k=2)[0][0] in {"EA_60E", "SBH_104D"}

    def test_finds_by_section_number(self):
        index = bm25.Bm25Index.build(self.CHUNKS)
        assert index.search("section 60E", k=1)[0][0] == "EA_60E"

    def test_a_jurisdiction_filter_excludes_other_territories(self):
        index = bm25.Bm25Index.build(self.CHUNKS)
        hits = index.search("annual leave", k=5, jurisdictions=["Sabah", "Malaysia"])
        assert [chunk_id for chunk_id, _ in hits if chunk_id.startswith("EA")] == []
        assert hits[0][0] == "SBH_104D"

    def test_no_matching_words_returns_nothing(self):
        index = bm25.Bm25Index.build(self.CHUNKS)
        assert index.search("boss fired me", k=5) == []

    def test_ties_are_broken_by_chunk_id_so_results_are_stable(self):
        index = bm25.Bm25Index.build(self.CHUNKS)
        first = index.search("paid annual leave of eight days", k=5)
        assert first == index.search("paid annual leave of eight days", k=5)
        tied = [c for c, s in first if s == first[0][1]]
        assert tied == sorted(tied)

    def test_save_and_load_round_trip(self, tmp_path):
        index = bm25.Bm25Index.build(self.CHUNKS)
        index.save(tmp_path)
        loaded = bm25.Bm25Index.load(tmp_path)
        assert loaded.search("section 60E", k=3) == index.search("section 60E", k=3)
