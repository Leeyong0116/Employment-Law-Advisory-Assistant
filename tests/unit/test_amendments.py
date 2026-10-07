"""Tests for src/ingestion/amendments.py.

Fixture lines are copied from extract_pages() output over Act A1754; the
comments give the printed page.
"""
import pathlib

import pytest
import yaml

from src.ingestion import amendments


class TestReadTitle:
    @pytest.mark.parametrize(
        "title, action, targets",
        [
            ("Amendment of section 84", "amend", ["84"]),  # p.21
            ("Substitution of section 2b", "substitute", ["2B"]),  # p.8
            ("Deletion of sections 8c, 8d and 8e", "delete", ["8C", "8D", "8E"]),  # p.9
            ("New sections 19a and 19b", "insert", ["19A", "19B"]),  # p.16
            ("New section 10d", "insert", ["10D"]),  # p.15
            ("Deletion of Chapter XIa", "delete_chapter", ["Chapter XIA"]),  # p.20
            ("Amendment of Chapter XIb", "amend_heading", ["Chapter XIB"]),  # p.21
            ("New Part IVa", "insert_part", ["Part IVA"]),  # p.39
            ("Substitution of Schedule", "substitute_schedule", ["SCHEDULE"]),  # p.83
            ("General amendments", "general", []),  # p.3
            ("Saving and transitional", "other", []),  # p.88
        ],
    )
    def test_titles(self, title, action, targets):
        assert amendments.read_title(title) == (action, targets)


class TestNarrowing:
    def test_a_named_subsection_narrows_the_link(self):
        # p.9: "Subsection 8i(1) of the Ordinance is amended—"
        assert amendments.narrow_target("Subsection 8i(1) of the Ordinance is amended—") == ("8I", "(1)", None)

    def test_an_instruction_paragraph_naming_a_subsection(self):
        # p.21: "(a) by substituting for subsection (1) the following subsection:"
        assert amendments.narrow_target("(a)\t by substituting for subsection (1) the following subsection:") == (
            None, "(1)", None
        )

    def test_a_named_definition_narrows_the_link(self):
        # p.4: "(iii) in the definition of “confinement”, by substituting ..."
        assert amendments.narrow_target("(iii)\t in the definition of “confinement”, by substituting") == (
            None, None, "confinement"
        )

    def test_an_insertion_after_a_definition_does_not_target_it(self):
        # p.4: inserting "apprentice" after "agricultural undertaking" leaves
        # "agricultural undertaking" itself unchanged.
        text = "(i)\t by inserting after the definition of “agricultural undertaking” the following"
        assert amendments.narrow_target(text) == (None, None, None)


CONFIG = yaml.safe_load(pathlib.Path("config/config.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def linked():
    docs = {d["id"]: d for d in CONFIG["corpus"]["documents"]}
    raw = pathlib.Path(CONFIG["corpus"]["raw_dir"])
    if not (raw / docs["sarawak_amendment_act_2025"]["file"]).exists():
        pytest.skip("source PDFs not present")
    from src.ingestion import schedules, sections

    principal, _ = sections.parse_document(docs["labour_ordinance_sarawak"], raw)
    principal += schedules.parse_document_schedules(docs["labour_ordinance_sarawak"], CONFIG)
    amending, report = amendments.parse_amending_act(docs["sarawak_amendment_act_2025"], CONFIG)
    link_report = amendments.link(principal, amending)
    return (
        {c["chunk_id"]: c for c in principal},
        {c["chunk_id"]: c for c in amending},
        report,
        link_report,
    )


@pytest.mark.corpus
class TestAgainstTheRealCorpus:
    def test_all_75_sections_are_found(self, linked):
        _, _, report, _ = linked
        assert report["sections"] == 75
        assert report["missing"] == []

    def test_maternity_leave_example_from_claude_md(self, linked):
        # Cap. 76 s.84 says sixty days; A1754 s.24 substitutes the scheme.
        principal, amending, _, _ = linked
        s84_1 = principal["SWK76_s84_1"]
        assert s84_1["status"] == "superseded"
        assert s84_1["amended_by"]
        assert all(a.startswith("A1754_s24") for a in s84_1["amended_by"])
        source = amending[s84_1["amended_by"][0]]
        assert "SWK76_s84_1" in source["amends"]

    def test_a_definition_level_link(self, linked):
        principal, _, _, _ = linked
        confinement = next(c for c in principal.values() if c.get("defined_term") == "confinement")
        assert confinement["status"] == "superseded"
        assert any(a.startswith("A1754_s3") for a in confinement["amended_by"])

    def test_a_deleted_definition_is_its_own_chunk_and_link(self, linked):
        # p.6: "(ix) by deleting the definition of “family”;" is short but is
        # the only record of the deletion, so it must not be merged away.
        principal, amending, _, _ = linked
        family = principal["SWK76_s2_1_def_family"]
        assert family["status"] == "deleted" and family["deleted_by"] == "Act A1754"
        assert family["amended_by"] == ["A1754_s3_a_ix"]

    def test_inserting_a_definition_changes_nothing_that_exists(self, linked):
        # (iv) inserts "constructional contractor" after "confinement";
        # (xvii) inserts after the *deleted* definition of "ship".
        _, amending, _, _ = linked
        assert amending["A1754_s3_a_iv"]["amends"] == []
        assert amending["A1754_s3_a_xvii"]["amends"] == []

    def test_roman_sub_paragraphs_are_not_read_as_letters(self, linked):
        # "(i)" under "(a)" must not be taken as the ninth lettered paragraph.
        _, amending, _, _ = linked
        ids = [c for c in amending if c.startswith("A1754_s3_")]
        assert "A1754_s3_a_ii" in ids and "A1754_s3_ii" not in ids

    def test_a_sub_paragraph_inherits_its_parents_target(self, linked):
        # "(d) in subsection (6)—" / "(i) by inserting after the word ..."
        _, amending, _, _ = linked
        assert amending["A1754_s3_d"]["amends"] == ["SWK76_s2_6"]

    def test_deleted_sections_are_marked_deleted_by_a1754(self, linked):
        principal, _, _, _ = linked
        for section in ("8C", "8D", "8E"):
            chunks = [c for c in principal.values() if c["section"] == section]
            assert chunks, section
            assert all(c["status"] == "deleted" and c["deleted_by"] == "Act A1754" for c in chunks)

    def test_part_iva_is_split_per_inserted_section_and_not_in_force(self, linked):
        _, amending, _, _ = linked
        part = [c for c in amending.values() if c["section"] == "52"]
        assert len(part) > 20
        assert all(c["status"] == "not_yet_in_force" for c in part)
        assert any(c["inserts"] == ["122A"] for c in part)

    def test_everything_else_in_a1754_is_in_force(self, linked):
        _, amending, _, _ = linked
        others = [c for c in amending.values() if c["section"] != "52"]
        assert {c["status"] for c in others} == {"in_force"}

    def test_unchanged_sections_are_untouched(self, linked):
        principal, _, _, _ = linked
        assert principal["SWK76_s1"]["status"] == "in_force"
        assert principal["SWK76_s1"]["amended_by"] == []

    def test_every_link_resolves(self, linked):
        principal, amending, _, link_report = linked
        for c in amending.values():
            for target in c["amends"]:
                assert target in principal, (c["chunk_id"], target)
        for c in principal.values():
            for source in c["amended_by"]:
                assert source in amending, (c["chunk_id"], source)
        assert link_report["unresolved"] == []
