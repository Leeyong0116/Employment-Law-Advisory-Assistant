"""Tests for src/ingestion/sections.py.

Fixture lines are copied from real extract_pages() output over data/raw;
comments name the document and printed page.
"""
import json
import pathlib

import pytest
import yaml

from src.ingestion import sections
from src.ingestion.sections import BodyLine


def _lines(text, page=0, printed=1):
    return [BodyLine(page, printed, ln) for ln in text.splitlines()]


class TestJoinLines:
    def test_wrapped_prose_is_joined_with_spaces(self):
        assert sections.join_lines(["Every employee shall be", "allowed a rest day."]) == (
            "Every employee shall be allowed a rest day."
        )

    def test_paragraph_markers_and_provisos_start_new_lines(self):
        text = sections.join_lines(
            [
                "notice if he has been so employed—",
                "(a) four weeks; or",
                "(b) eight weeks:",
                "Provided that this section shall not be taken to prevent either party",
                "from waiving his right.",
            ]
        )
        assert text.splitlines() == [
            "notice if he has been so employed—",
            "(a) four weeks; or",
            "(b) eight weeks:",
            "Provided that this section shall not be taken to prevent either party from waiving his right.",
        ]

    def test_a_marker_alone_on_its_line_joins_its_text(self):
        # Sarawak p.11 and Sabah put "(a)" on its own line.
        assert sections.join_lines(["(a)", "a child adopted"]) == "(a) a child adopted"

    def test_editorial_asterisks_are_removed(self):
        # EA p.13: "This Act shall apply to *Peninsular Malaysia only."
        assert sections.join_lines(["apply to *Peninsular Malaysia only."]) == (
            "apply to Peninsular Malaysia only."
        )

    def test_a_line_end_hyphen_joins_without_a_space(self):
        assert sections.join_lines(["a sub-", "contractor"]) == "a sub-contractor"


class TestSplitSubsections:
    def test_sequential_markers_split(self):
        parts = sections.split_subsections(
            _lines("(1) This Act may be cited.\n (2) This Act shall apply.")
        )
        assert [(m, [l.text.strip() for l in ls]) for m, ls in parts] == [
            ("(1)", ["This Act may be cited."]),
            ("(2)", ["This Act shall apply."]),
        ]

    def test_a_wrapped_cross_reference_is_not_a_new_subsection(self):
        # "(1)" at the start of a line inside (3) is a reference, not a marker.
        parts = sections.split_subsections(
            _lines("(1) A.\n(2) B under subsection\n(1) of section 3.\n(3) C.")
        )
        assert [m for m, _ in parts] == ["(1)", "(2)", "(3)"]
        assert "(1) of section 3." in [l.text for l in parts[1][1]]

    def test_lettered_subsections_follow_their_number(self):
        parts = sections.split_subsections(_lines("(1) A.\n(1A) B.\n(1B) C.\n(2) D."))
        assert [m for m, _ in parts] == ["(1)", "(1A)", "(1B)", "(2)"]

    def test_text_not_opening_with_1_is_undivided(self):
        parts = sections.split_subsections(_lines("Every employee shall be allowed\n(2) not a marker"))
        assert [m for m, _ in parts] == [None]

    def test_a_proviso_stays_in_its_subsection(self):
        # EA p.26, s.12(2) and its proviso.
        parts = sections.split_subsections(
            _lines(
                "(1) Either party may give notice.\n(2) The notice shall be—\n(a) four weeks:\n"
                "Provided that this section shall not be taken to prevent either party\n"
                "from waiving his right to a notice under this subsection.\n(3) Notwithstanding"
            )
        )
        second = " ".join(l.text for l in parts[1][1])
        assert "Provided that this section" in second
        assert parts[2][0] == "(3)"


class TestSplitDefinitions:
    def test_each_term_becomes_its_own_definition(self):
        # EA p.14.
        scope, defs = sections.split_definitions(
            _lines(
                "In this Act, unless the context otherwise requires—\n"
                "“apprentice” means any person who has entered into an\n"
                "apprenticeship contract;\n"
                " “day” means—\n"
                "(a) a continuous period of twenty-four hours; or\n"
                "(b) for the purposes of Part XII;\n"
                "“Director General” means the   Director   General   of   Labour\n"
                "appointed under subsection 3(1);"
            )
        )
        assert scope == "In this Act, unless the context otherwise requires—"
        assert [term for term, _ in defs] == ["apprentice", "day", "Director General"]
        assert "(b) for the purposes of Part XII;" in [l.text for l in defs[1][1]]

    def test_straight_quotes_and_a_qualifier_before_means(self):
        # Sabah p.14 and Sarawak p.11.
        _, defs = sections.split_definitions(
            _lines('"adopted", in reference to any child, means—\n(a) a child adopted')
        )
        assert [term for term, _ in defs] == ["adopted"]

    def test_a_quoted_word_that_does_not_define_is_not_a_split(self):
        # EA p.14: the "confinement" definition ends with a quoted word.
        _, defs = sections.split_definitions(
            _lines(
                "“confinement” means parturition after twenty-two weeks,\n"
                "“confined” shall be\nconstrued accordingly;\n“contract of service” means any agreement"
            )
        )
        assert [term for term, _ in defs] == ["confinement", "contract of service"]

    def test_text_without_definitions_returns_none(self):
        assert sections.split_definitions(_lines("Every employee shall be allowed")) == (None, [])


class TestPlaceholders:
    @pytest.mark.parametrize(
        "text, status, by",
        [
            ("(Deleted by *Act 40 of 1966).", "deleted", "Act 40 of 1966"),  # EA p.25
            ("(Omitted).", "omitted", None),  # EA p.29
            ("[Deleted by AA1238]", "deleted", "AA1238"),  # Sabah p.47
            ("[Deleted by Act A1237.]", "deleted", "Act A1237"),  # Sarawak p.24
            ("[Deleted Act A1237.]", "deleted", "Act A1237"),  # Sarawak, missing "by"
            ("(Deleted by Act A1651).", "deleted", "Act A1651"),  # EA p.44
        ],
    )
    def test_placeholder_spellings(self, text, status, by):
        assert sections.parse_placeholder(text) == (status, by)

    def test_real_text_is_not_a_placeholder(self):
        assert sections.parse_placeholder("Every employee shall be allowed") is None


class TestAnnotations:
    def test_sarawak_amendment_tags_are_lifted_out(self):
        kept, tags = sections.lift_annotations(
            _lines("safety of the employees.\n[Am. Act A1237.]\n[Mod. F.L.N. 1/2000;  Am. Act A1237.]")
        )
        assert [l.text for l in kept] == ["safety of the employees."]
        assert tags == ["[Am. Act A1237.]", "[Mod. F.L.N. 1/2000; Am. Act A1237.]"]


class TestCrossReferences:
    def test_internal_references_resolve_to_known_sections(self):
        text = "approved under subsection 29(2) and for the purposes of section 60I and sections 10 to 16"
        assert sections.internal_references(text, {"29", "60I", "10", "16"}) == [
            "s. 29(2)",
            "s. 60I",
            "s. 10",
            "s. 16",
        ]

    def test_a_section_of_another_act_is_not_internal(self):
        text = "under section 20 of the Industrial Relations Act 1967"
        assert sections.internal_references(text, {"20"}) == []

    def test_external_statutes_are_recorded(self):
        text = "in accordance with the Trade Unions Act 1959 [Act 262] and the Employment Act 1955"
        assert sections.external_references(text, own="Employment Act 1955") == [
            "Trade Unions Act 1959 [Act 262]"
        ]


# --------------------------------------------------------------------------
# Against the real corpus
# --------------------------------------------------------------------------

CONFIG = yaml.safe_load(pathlib.Path("config/config.yaml").read_text(encoding="utf-8"))


def _chunks_for(doc_id):
    doc = next(d for d in CONFIG["corpus"]["documents"] if d["id"] == doc_id)
    if not (pathlib.Path(CONFIG["corpus"]["raw_dir"]) / doc["file"]).exists():
        pytest.skip("source PDFs not present")
    chunks, report = sections.parse_document(doc, CONFIG["corpus"]["raw_dir"])
    return {c["chunk_id"]: c for c in chunks}, report


@pytest.fixture(scope="module")
def ea():
    return _chunks_for("employment_act_1955")


@pytest.fixture(scope="module")
def ira():
    return _chunks_for("industrial_relations_act_1967")


@pytest.fixture(scope="module")
def sabah():
    return _chunks_for("labour_ordinance_sabah")


@pytest.fixture(scope="module")
def sarawak():
    return _chunks_for("labour_ordinance_sarawak")


@pytest.mark.corpus
class TestAgainstTheRealCorpus:
    def test_no_section_is_missing(self, ea, ira, sabah, sarawak):
        for _, report in (ea, ira, sabah, sarawak):
            assert report["missing"] == [], report["doc_id"]

    def test_the_cp1_listing_1_example(self, ea):
        chunks, _ = ea
        c = chunks["EA1955_s59_1"]
        assert c["citation"] == "Employment Act 1955, s. 59(1)"
        assert c["part"] == "Part XII"
        assert c["section_title"] == "Rest day"
        assert c["jurisdiction"] == "Peninsular Malaysia and Labuan"
        assert c["content"].startswith("Every employee shall be allowed in each week a rest day")
        assert c["source_page"] == 53

    def test_a_proviso_stays_with_its_subsection(self, ea):
        chunks, _ = ea
        assert "Provided that this section shall not be taken to prevent" in chunks["EA1955_s12_2"]["content"]

    def test_deleted_and_omitted_sections_are_chunks(self, ea):
        chunks, _ = ea
        assert chunks["EA1955_s9"]["status"] == "deleted"
        assert chunks["EA1955_s9"]["deleted_by"] == "Act 40 of 1966"
        assert chunks["EA1955_s35"]["status"] == "deleted"
        assert chunks["EA1955_s17"]["status"] == "omitted"

    def test_definitions_are_split_and_flagged(self, ea):
        chunks, _ = ea
        wages = next(c for c in chunks.values() if c.get("defined_term") == "wages" and c["section"] == "2")
        assert wages["chunk_type"] == "definition"
        assert wages["definition_scope"].startswith("In this Act")
        assert wages["content"].startswith("“wages” means")

    def test_no_editorial_text_reaches_content(self, ea, ira, sarawak):
        for chunks, _ in (ea, ira, sarawak):
            for c in chunks.values():
                assert "*NOTE" not in c["content"], c["chunk_id"]
                assert "[Am. Act" not in c["content"], c["chunk_id"]
                assert "CAP. 76 (1948 ED.)" not in c["content"], c["chunk_id"]

    def test_ea_footnotes_become_in_force_notes(self, ea):
        chunks, report = ea
        assert report["unassigned_notes"] == 0
        assert chunks["EA1955_s1_2"]["in_force_notes"]

    def test_section_titles_do_not_leak_into_the_previous_chunk(self, ea):
        chunks, _ = ea
        # s.59 is followed by s.60 "Work on rest day".
        last_of_59 = [c for c in chunks.values() if c["section"] == "59"][-1]
        assert not last_of_59["content"].rstrip().endswith("Work on rest day")

    def test_sabah_not_yet_in_force_part(self, sabah):
        chunks, _ = sabah
        flagged = {c["section"] for c in chunks.values() if c["status"] == "not_yet_in_force"}
        assert "121A" in flagged and "121AU" in flagged

    def test_a_mid_sentence_definition_is_flagged(self, sarawak):
        # Sarawak s.84(11): "For the purposes of this section, “children”
        # means ...". It must be a definition chunk so it is co-retrieved with
        # s.84(1). (The 2006 text gives 60 days; the 98 days is in A1754.)
        chunks, _ = sarawak
        c = chunks["SWK76_s84_11_def_children"]
        assert c["chunk_type"] == "definition"
        assert "sixty consecutive days" in chunks["SWK76_s84_1"]["content"]

    def test_a_wrapped_reference_does_not_open_a_subsection(self, sabah):
        # Sabah s.130O(2)(i): "required under subsection" / "(3) of section 18;"
        chunks, _ = sabah
        assert "(3) of section 18" in chunks["SBH67_s130O_2"]["content"]
        assert chunks["SBH67_s130O_3"]["content"].startswith("Any such rule may provide a penalty")

    def test_a_deleted_sections_old_title_is_not_left_behind(self, ea):
        # EA s.81G is deleted but still prints its title above the placeholder.
        chunks, _ = ea
        tail = [c for c in chunks.values() if c["section"] == "81F"][-1]["content"]
        assert not tail.endswith("irrespective of wages of employee")
        assert chunks["EA1955_s81G"]["section_title"] == "Application of this Part irrespective of wages of employee"

    def test_every_chunk_has_citation_metadata(self, ea, ira, sabah, sarawak):
        for chunks, _ in (ea, ira, sabah, sarawak):
            for c in chunks.values():
                assert c["citation"] and c["source_page"] is not None, c["chunk_id"]
                assert c["content"].strip(), c["chunk_id"]
