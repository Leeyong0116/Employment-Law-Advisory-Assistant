"""Tests for src/ingestion/toc.py.

Fixture strings are copied from real extract_pages() output over data/raw,
not invented. Each docstring or comment names the document and page.
"""
import pathlib

import pytest
import yaml

from src.ingestion import toc


def _sections(entries):
    return [e.section for e in entries if e.kind == "section"]


def _by_id(entries):
    return {e.section: e for e in entries}


class TestEntryLayouts:
    def test_number_and_title_on_separate_lines(self):
        # EA p.3: the number and its title are separate text lines.
        page = "PART I\nPRELIMINARY\n Section\n1.\nShort title and application\n      2.\nInterpretation"
        entries = toc.parse_toc([page], "ea")
        assert [(e.section, e.title) for e in entries] == [
            ("1", "Short title and application"),
            ("2", "Interpretation"),
        ]

    def test_number_and_title_on_one_line(self):
        # EA p.3 and Sabah p.1 put both on one line.
        page = "PART I\nPRELIMINARY\n3.   Appointment of officers\n7A. Director’s power to inquire into complaints"
        entries = toc.parse_toc([page], "x")
        assert [(e.section, e.title) for e in entries] == [
            ("3", "Appointment of officers"),
            ("7A", "Director’s power to inquire into complaints"),
        ]

    def test_a_wrapped_title_is_joined(self):
        # EA p.3: the s.8 title wraps onto a second line.
        page = (
            "PART II\nCONTRACTS OF SERVICE\n8.\n"
            "Contracts of service not to restrict rights of employees to join, participate in\n"
            "or organize trade unions\n9.\n(Deleted)"
        )
        entries = _by_id(toc.parse_toc([page], "ea"))
        assert entries["8"].title == (
            "Contracts of service not to restrict rights of employees to join, "
            "participate in or organize trade unions"
        )

    def test_a_title_continues_across_a_page_break(self):
        page_one = "PART II\nCONTRACTS\n10.\nContracts to be in writing and"
        page_two = "Section\nto include provision for termination\n11.\nProvision as to termination"
        entries = _by_id(toc.parse_toc([page_one, page_two], "x"))
        assert entries["10"].title == "Contracts to be in writing and to include provision for termination"

    def test_section_ids_are_upper_cased(self):
        page = "PART I\nPRELIMINARY\n8a.\nInserted section"
        assert _sections(toc.parse_toc([page], "x")) == ["8A"]


class TestRanges:
    def test_a_hyphen_range_expands_to_every_section(self):
        # EA p.5: "34-36.    (Deleted)"
        page = "PART VIII\nEMPLOYMENT OF WOMEN\n34-36.    (Deleted)"
        entries = toc.parse_toc([page], "ea")
        assert _sections(entries) == ["34", "35", "36"]
        assert all(e.status == "deleted" for e in entries)

    def test_a_range_whose_status_is_on_the_next_line(self):
        # EA p.6: " 45-56." then " (Deleted)"
        page = "PART X\nEMPLOYMENT OF CHILDREN AND YOUNG PERSONS\n 45-56.\n (Deleted)"
        entries = toc.parse_toc([page], "ea")
        assert _sections(entries) == [str(n) for n in range(45, 57)]
        assert all(e.status == "deleted" for e in entries)

    def test_an_em_dash_range_keeps_its_instrument(self):
        # Sabah p.3: "19 — 33. [Deleted by AA1238]"
        page = "PART II — CONTRACTS OF SERVICE\n19 — 33. [Deleted by AA1238]"
        entries = toc.parse_toc([page], "sabah")
        assert len(entries) == 15
        assert {e.deleted_by for e in entries} == {"AA1238"}


class TestPlaceholderStatus:
    @pytest.mark.parametrize(
        "line, status, deleted_by",
        [
            ("9.\n(Deleted)", "deleted", None),  # EA p.3
            ("17.\n(Omitted)", "omitted", None),  # EA p.4
            ("7C. [Deleted by AA1753]", "deleted", "AA1753"),  # Sabah p.1
            ("5.\n[Deleted by Act A1237.]", "deleted", "Act A1237"),  # Sarawak p.1
            ("6.\nSaving of existing contracts", "listed", None),
        ],
    )
    def test_status_spellings(self, line, status, deleted_by):
        (entry,) = toc.parse_toc([f"PART I\nPRELIMINARY\n{line}"], "x")
        assert entry.status == status
        assert entry.deleted_by == deleted_by

    def test_a_placeholder_has_no_title(self):
        (entry,) = toc.parse_toc(["PART I\nPRELIMINARY\n9.\n(Deleted)"], "x")
        assert entry.title is None


class TestHeadings:
    def test_part_and_its_title_are_tracked(self):
        # EA p.6: the Part number and title are separate lines.
        page = "PART XIIA\nTERMINATION, LAY-OFF AND RETIREMENT BENEFITS\n60J.\nTermination, lay-off and retirement benefits"
        (entry,) = toc.parse_toc([page], "ea")
        assert entry.part == "Part XIIA"
        assert entry.chapter is None

    def test_inline_part_title_and_chapters(self):
        # Sabah p.1: "PART I — LABOUR DEPARTMENT", then "CHAPTER 1".
        page = (
            "PART I — LABOUR DEPARTMENT\nCHAPTER 1\nPreliminary and interpretation\n Section\n"
            "1. Short Title\nCHAPTER IIA\nComplaints and Inquiries\n7A. Director’s power to inquire into complaints"
        )
        entries = _by_id(toc.parse_toc([page], "sabah"))
        assert (entries["1"].part, entries["1"].chapter) == ("Part I", "Chapter 1")
        assert (entries["7A"].part, entries["7A"].chapter) == ("Part I", "Chapter IIA")

    def test_a_new_part_clears_the_chapter(self):
        page = "PART I\nX\nCHAPTER II\nY\n3. Officers\nPART II\nZ\n10. Guaranteed week"
        entries = _by_id(toc.parse_toc([page], "x"))
        assert entries["10"].chapter is None

    def test_hyphenated_and_extra_spaced_part_headings(self):
        # Sabah p.11 uses a hyphen; Sarawak p.1 pads with spaces ("PART   I").
        page = "PART   I\nLABOUR  DEPARTMENT\n1.\nShort title\nPART V - PROCEDURE, OFFENCES\n122. [Deleted by AA1238]"
        entries = _by_id(toc.parse_toc([page], "x"))
        assert entries["1"].part == "Part I"
        assert entries["122"].part == "Part V"

    def test_a_wrapped_part_title_is_not_read_as_a_section(self):
        # EA p.5: the Part VII title wraps.
        page = "PART VII\nPRINCIPALS, CONTRACTORS, SUB-CONTRACTORS AND\n CONTRACTORS FOR LABOUR\n33.\nLiability"
        assert _sections(toc.parse_toc([page], "ea")) == ["33"]

    def test_a_deleted_chapter_heading_is_not_an_entry(self):
        # Sabah p.4: "CHAPTER VIII" / "[Deleted by AA1238]" then the range.
        page = "PART III\n[Deleted by AA1238]\nCHAPTER VIII\n[Deleted by AA1238]\n44 — 54. [Deleted by AA1238]"
        assert _sections(toc.parse_toc([page], "sabah")) == [str(n) for n in range(44, 55)]


class TestNoise:
    def test_the_title_block_before_the_heading_is_skipped(self):
        # EA p.3 opens with the Act's title block.
        page = "LAWS OF MALAYSIA\nAct 265\nEMPLOYMENT ACT 1955\nARRANGEMENT OF SECTIONS\nPART I\nPRELIMINARY\n1.\nShort title"
        assert _sections(toc.parse_toc([page], "ea")) == ["1"]

    @pytest.mark.parametrize(
        "furniture",
        [
            "4                                    Laws of Malaysia\n               ACT 265\n  Section\n\\\\",  # EA p.4
            "Laws of Malaysia                          ACT 177",  # IRA p.4
            "CAP. 76 (1948 ED.)",  # Sarawak p.2
            "____________________________",  # Sabah p.1
        ],
    )
    def test_leaked_running_headers_are_dropped(self, furniture):
        page_one = "PART I\nPRELIMINARY\n10.\nContracts to be in writing"
        page_two = f"{furniture}\n11.\nProvision as to termination of contracts"
        entries = _by_id(toc.parse_toc([page_one, page_two], "x"))
        assert entries["10"].title == "Contracts to be in writing"
        assert entries["11"].title == "Provision as to termination of contracts"

    def test_an_unrecognised_line_before_any_heading_is_an_error(self):
        with pytest.raises(toc.TocParseError):
            toc.parse_toc(["something unexpected\nPART I\nX\n1. Short title"], "x")

    def test_a_continuation_starting_with_a_digit_is_an_error(self):
        # A malformed number must never be glued silently onto a title.
        with pytest.raises(toc.TocParseError):
            toc.parse_toc(["PART I\nX\n1.\nShort title\n2 Interpretation"], "x")


class TestNotYetInForce:
    def test_the_marked_range_is_flagged_by_document_order(self):
        # Sabah p.9. Letter ranges cannot be expanded arithmetically, so the
        # flag runs from the first id to the last id as they appear.
        page = (
            "PART IV — PROVISIONS\n121. [Deleted by AA1238]\n"
            "(NOT YET IN FORCE) (Section 121A — 121AU)\n"
            "PART IVA — SPECIAL PROVISIONS RELATING TO EMPLOYEES’ MINIMUM STANDARDS OF\n"
            "121A. Interpretation\n121Z. Requirement for accommodation\n121AA. Functions\n121AU. Failure to comply\n"
            "PART V - PROCEDURE\n122. [Deleted by AA1238]"
        )
        entries = _by_id(toc.parse_toc([page], "sabah"))
        assert [s for s, e in entries.items() if e.not_yet_in_force] == ["121A", "121Z", "121AA", "121AU"]

    def test_a_range_that_never_closes_is_an_error(self):
        page = "PART IV\nX\n(NOT YET IN FORCE) (Section 121A — 121AU)\n121A. Interpretation"
        with pytest.raises(toc.TocParseError):
            toc.parse_toc([page], "sabah")


class TestSchedules:
    def test_schedules_become_schedule_entries(self):
        # EA p.11.
        page = "PART XIX\nREPEAL AND SAVING\nSection\n 103.\nRepeal and saving\nFIRST SCHEDULE\nSECOND SCHEDULE"
        entries = toc.parse_toc([page], "ea")
        assert [(e.kind, e.section) for e in entries] == [
            ("section", "103"),
            ("schedule", "FIRST SCHEDULE"),
            ("schedule", "SECOND SCHEDULE"),
        ]


class TestSanityChecks:
    def test_a_duplicate_section_is_an_error(self):
        with pytest.raises(toc.TocParseError):
            toc.parse_toc(["PART I\nX\n1. A\n1. B"], "x")

    def test_a_decreasing_section_number_is_an_error(self):
        with pytest.raises(toc.TocParseError):
            toc.parse_toc(["PART I\nX\n12. A\n11. B"], "x")

    def test_letter_suffixes_are_not_order_checked(self):
        # EA has 60F, 60FA, 60G; Sabah has 121Z then 121AA. No single letter
        # ordering fits both, so only the number is checked.
        page = "PART I\nX\n60F. A\n60FA. B\n60G. C\n121Z. D\n121AA. E"
        assert _sections(toc.parse_toc([page], "x")) == ["60F", "60FA", "60G", "121Z", "121AA"]


# --------------------------------------------------------------------------
# Against the real corpus
# --------------------------------------------------------------------------

CONFIG = yaml.safe_load(pathlib.Path("config/config.yaml").read_text(encoding="utf-8"))


def _inventory_for(doc_id):
    doc = next(d for d in CONFIG["corpus"]["documents"] if d["id"] == doc_id)
    path = pathlib.Path(CONFIG["corpus"]["raw_dir"]) / doc["file"]
    if not path.exists():
        pytest.skip("source PDFs not present")
    return toc.inventory_for_document(doc, CONFIG["corpus"]["raw_dir"])


@pytest.fixture(scope="module")
def ea():
    return _inventory_for("employment_act_1955")


@pytest.fixture(scope="module")
def ira():
    return _inventory_for("industrial_relations_act_1967")


@pytest.fixture(scope="module")
def sabah():
    return _inventory_for("labour_ordinance_sabah")


@pytest.fixture(scope="module")
def sarawak():
    return _inventory_for("labour_ordinance_sarawak")


@pytest.mark.corpus
class TestAgainstTheRealCorpus:
    def test_every_document_with_contents_pages_declares_them(self):
        declared = {d["id"] for d in CONFIG["corpus"]["documents"] if "toc_pages" in d}
        assert declared == {
            "employment_act_1955",
            "industrial_relations_act_1967",
            "labour_ordinance_sabah",
            "labour_ordinance_sarawak",
        }

    def test_ea(self, ea):
        sections = _sections(ea)
        by_id = _by_id(ea)
        assert sections[0] == "1" and sections[-1] == "103"
        assert "60FA" in sections
        assert all(by_id[s].status == "deleted" for s in ("34", "35", "36"))
        assert by_id["17"].status == "omitted"
        assert by_id["60FA"].part == "Part XII"
        assert [e.section for e in ea if e.kind == "schedule"] == ["FIRST SCHEDULE", "SECOND SCHEDULE"]

    def test_ira(self, ira):
        sections = _sections(ira)
        by_id = _by_id(ira)
        assert sections[0] == "1" and sections[-1] == "63"
        for s in ("12A", "12B", "51A", "51B", "51C", "51D", "51E", "51F"):
            assert s in sections
        assert by_id["33A"].status == "deleted"

    def test_sabah(self, sabah):
        sections = _sections(sabah)
        by_id = _by_id(sabah)
        assert sections[0] == "1" and sections[-1] == "132"
        assert by_id["7C"].deleted_by == "AA1753"
        assert by_id["7A"].chapter == "Chapter IIA"

    def test_sabah_not_yet_in_force_range_matches_config(self, sabah):
        doc = next(d for d in CONFIG["corpus"]["documents"] if d["id"] == "labour_ordinance_sabah")
        (exception,) = doc["commencement_exceptions"]
        flagged = [e.section for e in sabah if e.not_yet_in_force]
        assert f"{flagged[0]}-{flagged[-1]}" == exception["source_section"]
        assert len(flagged) == 47  # 121A..121Z is 26, 121AA..121AU is 21

    def test_sarawak(self, sarawak):
        sections = _sections(sarawak)
        by_id = _by_id(sarawak)
        assert sections[0] == "1"
        assert by_id["5"].deleted_by == "Act A1237"
        assert "130A" in sections
        assert by_id["8A"].chapter == "Chapter IIA"

    def test_section_counts(self, ea, ira, sabah, sarawak):
        # Verified 2026-10-07 two ways: an independent line count over raw
        # PyMuPDF text of the contents pages (ranges expanded) gave the same
        # totals, and every whole number from 1 to the last section is
        # present. A change here means a regression, not a new section.
        counts = {
            "ea": (ea, 158, 27, 4),
            "ira": (ira, 83, 4, 0),
            "sabah": (sabah, 275, 88, 0),
            "sarawak": (sarawak, 205, 79, 0),
        }
        for name, (entries, total, deleted, omitted) in counts.items():
            sections = [e for e in entries if e.kind == "section"]
            assert len(sections) == total, name
            assert sum(e.status == "deleted" for e in sections) == deleted, name
            assert sum(e.status == "omitted" for e in sections) == omitted, name

    def test_no_whole_number_section_is_missing(self, ea, ira, sabah, sarawak):
        for entries in (ea, ira, sabah, sarawak):
            numbers = {toc._section_number(s) for s in _sections(entries)}
            assert numbers == set(range(1, max(numbers) + 1)), entries[0].doc_id

    def test_sarawak_contents_list_no_schedule(self, sarawak):
        # True of the source: Cap. 76's contents pages stop at the sections,
        # and its single SCHEDULE appears only in the body (PDF page 109). The
        # validator must add it from the body, not expect it from here.
        assert not any(e.kind == "schedule" for e in sarawak)

    def test_no_document_loses_a_placeholder(self, ea, ira, sabah, sarawak):
        # Every placeholder line in the contents must survive as an entry.
        for entries in (ea, ira, sabah, sarawak):
            assert any(e.status != "listed" for e in entries)
