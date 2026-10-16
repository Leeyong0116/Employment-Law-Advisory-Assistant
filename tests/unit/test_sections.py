"""Tests for src/ingestion/sections.py.

Fixture lines are copied from real extract_pages() output over data/raw;
comments name the document and printed page.
"""
import json
import pathlib

import pytest
import yaml

from src.ingestion import sections, toc
from src.ingestion.extract import Page
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

    def test_a_new_sentence_opens_a_subsection_even_without_a_full_stop(self):
        # Sabah p.106, s.121I: the source omits the full stop after (3)(b),
        # but "(4) Any employer" plainly starts a new subsection.
        parts = sections.split_subsections(
            _lines("(1) A.\n(2) B.\n(3) supply of milk —\n(a) in sufficient quantity; and\n"
                   "(b) of good quality\n(4) Any employer who fails to comply")
        )
        assert [m for m, _ in parts] == ["(1)", "(2)", "(3)", "(4)"]

    def test_a_wrapped_reference_followed_by_lower_case_is_still_not_split(self):
        # Sabah s.130O: "required under subsection" / "(3) of section 18;"
        parts = sections.split_subsections(
            _lines("(1) A.\n(2) B prescribing the contents required under subsection\n(3) of section 18;")
        )
        assert [m for m, _ in parts] == ["(1)", "(2)"]

    def test_a_bare_marker_looks_at_the_next_line(self):
        # Sabah puts the marker alone: "(2)" / "[Deleted by AA1753]" or a sentence.
        parts = sections.split_subsections(_lines("(1) A of good quality\n(2)\nThe Director may"))
        assert [m for m, _ in parts] == ["(1)", "(2)"]

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

    def test_a_document_never_lists_itself_as_external(self):
        # Overtime Regulations reg. 1: the pattern cannot read "(Limitation",
        # so it picks up only the tail of the document's own name.
        own = "Employment (Limitation of Overtime Work) Regulations 1980"
        text = f"These Regulations may be cited as the {own}."
        assert sections.external_references(text, own=own) == []

    def test_regulations_refer_to_each_other_as_regulations(self):
        # Termination Regulations reg. 3(1)(b) and 5(1).
        text = "calculated in accordance with regulation 6 ... within the meaning of regulation 5."
        assert sections.internal_references(text, {"5", "6"}, label="reg.") == ["reg. 6", "reg. 5"]

    def test_a_section_in_regulations_is_the_parent_acts_not_internal(self):
        # Termination Regulations reg. 4(1)(c): "section 13 (2)" is EA s.13(2),
        # and the Regulations also have a regulation 13. Linking it would be wrong.
        text = "other than under section 13 (2) or for the reasons specified in section 14 (3) of the Act."
        assert sections.internal_references(text, {"13", "14"}, label="reg.") == []


class TestInlineTitles:
    """Regulations print the title on the number's line: "2. Interpretation."."""

    def test_a_one_line_title_is_taken_off_the_text(self):
        lines = _lines("Limit of overtime work.\nThe limit of overtime work for the purpose")
        title, rest = sections.split_inline_title(lines, "Limit of overtime work.")
        assert title == "Limit of overtime work"
        assert [ln.text for ln in rest] == ["The limit of overtime work for the purpose"]

    def test_a_wrapped_title_ends_at_the_first_full_stop(self):
        # Termination Regulations p.3; the contents say "of lay-off", the body "or lay-off".
        lines = _lines(
            "General provisions for the entitlement of employees to termination or lay-off benefits\n"
            "payment.\n(1) Subject to these Regulations, an employer shall be liable"
        )
        title, rest = sections.split_inline_title(
            lines, "General provisions for the entitlement of employees to termination of lay-off benefits payment."
        )
        assert title == "General provisions for the entitlement of employees to termination or lay-off benefits payment"
        assert rest[0].text.startswith("(1) Subject to these Regulations")

    def test_text_that_does_not_match_the_title_is_left_alone(self):
        lines = _lines("The limit of overtime work for the purpose.\nMore text.")
        title, rest = sections.split_inline_title(lines, "Citation.")
        assert title is None and rest == lines


REG_DOC = {
    "id": "ot", "short_name": "Employment (Limitation of Overtime Work) Regulations 1980",
    "act_number": "P.U. (A) 339/1983", "chunk_prefix": "OT1980",
    "jurisdiction_label": "Peninsular Malaysia and Labuan", "source_version": "v", "as_at": "1991-10-17",
    "source_url": None, "provision_label": "reg.", "inline_titles": True, "body_start_page": 0,
}


class TestRegulationDocument:
    def _parse(self):
        # Overtime Regulations p.1, as extract_pages() returns it.
        page = Page(0, 1, (
            "1. Citation.\nThese Regulations may be cited as the Employment (Limitation of Overtime Work)\n"
            "Regulations 1980.\n2. Limit of overtime work.\n"
            "The limit of overtime work for the purpose of section 60A (4) (a) of the Act shall be a\n"
            "total of one hundred and four hours in any one month."
        ))
        inventory = toc.inventory_for_document({"id": "ot", "declared_sections": [
            {"section": "1", "title": "Citation."}, {"section": "2", "title": "Limit of overtime work."}]}, "unused")
        chunks, report, _ = sections.parse_body(REG_DOC, [page], inventory)
        return {c["chunk_id"]: c for c in chunks}, report

    def test_citations_and_ids_name_regulations(self):
        chunks, _ = self._parse()
        assert list(chunks) == ["OT1980_r1", "OT1980_r2"]
        assert chunks["OT1980_r2"]["citation"] == "Employment (Limitation of Overtime Work) Regulations 1980, reg. 2"

    def test_the_title_is_metadata_not_content(self):
        chunks, report = self._parse()
        assert chunks["OT1980_r2"]["section_title"] == "Limit of overtime work"
        assert chunks["OT1980_r2"]["content"].startswith("The limit of overtime work")
        assert report["titles_unmatched"] == []

    def test_the_previous_regulation_keeps_its_last_line(self):
        # The title-above-the-number search would take "Regulations 1980." as
        # the title of reg. 2.
        chunks, _ = self._parse()
        assert chunks["OT1980_r1"]["content"] == (
            "These Regulations may be cited as the Employment (Limitation of Overtime Work) Regulations 1980."
        )


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


@pytest.fixture(scope="module")
def overtime():
    return _chunks_for("ea_overtime_regulations_1980")


@pytest.fixture(scope="module")
def termination():
    return _chunks_for("ea_termination_benefits_regulations_1980")


@pytest.mark.corpus
class TestEmploymentActRegulations:
    def test_every_regulation_is_found_and_titled(self, overtime, termination):
        for _, report in (overtime, termination):
            assert report["missing"] == [] and report["titles_unmatched"] == [], report["doc_id"]

    def test_the_overtime_limit(self, overtime):
        chunks, _ = overtime
        c = chunks["OT1980_r2"]
        assert c["citation"] == "Employment (Limitation of Overtime Work) Regulations 1980, reg. 2"
        assert c["content"] == (
            "The limit of overtime work for the purpose of section 60A (4) (a) of the Act shall be a "
            "total of one hundred and four hours in any one month."
        )
        assert c["jurisdiction"] == "Peninsular Malaysia and Labuan"
        assert c["source_page"] == 1  # PDF page: the source prints none
        assert any(n.startswith("*Revised and published") for n in c["in_force_notes"])

    def test_the_benefit_rates_cross_a_page_whole(self, termination):
        chunks, _ = termination
        c = chunks["TLB1980_r6_1"]
        assert c["citation"] == "Employment (Termination and Lay-Off Benefits) Regulations 1980, reg. 6(1)"
        for words in ("ten days’ wages", "fifteen days’ wages", "twenty days’ wages",
                      "and pro-rata as respect an incomplete year"):
            assert words in c["content"]
        assert (c["source_page"], c["source_page_end"]) == (4, 5)

    def test_a_proviso_across_a_page_break_stays(self, termination):
        chunks, _ = termination
        assert "Provided that the period of employment immediately prior" in chunks["TLB1980_r4_2"]["content"]

    def test_the_footnote_never_reaches_a_definition(self, termination):
        chunks, _ = termination
        c = chunks["TLB1980_r2_def_relevant_date"]
        assert c["chunk_type"] == "definition"
        assert c["definition_scope"] == "In these Regulations unless the context otherwise requires —"
        assert "(b) in relation to a lay-off" in c["content"]
        for c in chunks.values():
            assert "published as PU" not in c["content"], c["chunk_id"]
            assert "Amending law" not in c["content"], c["chunk_id"]

    def test_titles_stay_out_of_content(self, termination):
        chunks, _ = termination
        assert chunks["TLB1980_r1"]["content"].startswith("These Regulations may be cited")
        assert chunks["TLB1980_r3_1"]["section_title"].startswith("General provisions for the entitlement")
        assert chunks["TLB1980_r3_1"]["content"].startswith("Subject to these Regulations")

    def test_source_wording_is_kept_verbatim(self, termination):
        # A retyped source: its typos are the source's, never corrected here.
        chunks, _ = termination
        assert "may be death with" in chunks["TLB1980_r13"]["content"]

    def test_references_are_to_regulations(self, termination):
        chunks, _ = termination
        assert chunks["TLB1980_r3_1"]["cross_references_internal"] == ["reg. 6", "reg. 5"]
        assert chunks["TLB1980_r4_1"]["cross_references_internal"] == []
