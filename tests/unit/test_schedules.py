"""Tests for src/ingestion/schedules.py.

Fixture lines and coordinates come from the real PDFs; comments name the
document and page.
"""
import pathlib

import pytest
import yaml

from src.ingestion import schedules
from src.ingestion.schedules import Cell
from src.ingestion.sections import BodyLine


def _lines(text):
    return [BodyLine(0, 1, ln) for ln in text.splitlines()]


class TestSplitSchedules:
    def test_split_at_headings_and_stop_at_end_matter(self):
        # IRA pp.73-75.
        lines = _lines(
            "*FIRST SCHEDULE\nESSENTIAL SERVICES\n1. Electricity services.\n"
            "SECOND SCHEDULE\nFACTORS FOR CONSIDERATION\n1. The financial implications.\n"
            "LAWS OF MALAYSIA\nAct 177\nINDUSTRIAL RELATIONS ACT 1967\nLIST OF AMENDMENTS\nAmending law"
        )
        parts = schedules.split_schedules(lines)
        assert [name for name, _ in parts] == ["FIRST SCHEDULE", "SECOND SCHEDULE"]
        assert [ln.text for ln in parts[1][1]][-1] == "1. The financial implications."

    def test_a_short_title_block_does_not_eat_statute_text(self):
        # Sarawak pp.111-112: the amendment list is headed by two lines, and
        # the Schedule's last line "payment." must survive.
        lines = _lines(
            "SCHEDULE\n3. For the purpose of this Schedule, “wages” means\nsubsistence allowance and overtime\n"
            "payment.\nLABOUR ORDINANCE\nChapter  76 (1958 Ed.)\nLIST  OF  AMENDMENTS\nAmending Law"
        )
        (_, part), = schedules.split_schedules(lines)
        assert part[-1].text == "payment."

    def test_a_bare_schedule_heading(self):
        # Sarawak Cap. 76 has one schedule, headed just "SCHEDULE".
        parts = schedules.split_schedules(_lines("SCHEDULE\n[Subsection (2) of section 2]\n1."))
        assert parts[0][0] == "SCHEDULE"


class TestTwoColumnRows:
    def test_exclusions_stay_with_the_sub_item_they_align_with(self):
        # EA First Schedule pp.112-113: "Part XII" sits level with item (4)
        # (seamen) and the long list level with item (5) (domestic employees).
        cells = [
            Cell(111, 240, "left", "2. Any person who, irrespective of the amount of"),
            Cell(111, 275, "left", "which—"),
            Cell(111, 298, "left", "(1) he is engaged in manual labour including"),
            Cell(111, 309, "left", "such labour as an artisan or apprentice:"),
            Cell(111, 600, "left", "(4) he is engaged in any capacity in any vessel"),
            Cell(111, 600, "right", "Part XII"),
            Cell(111, 612, "left", "registered in Malaysia and who—"),
            Cell(112, 111, "left", "(a) is not an officer certificated under the"),
            Cell(112, 272, "left", "(5) he is engaged as a domestic employee."),
            Cell(112, 272, "right", "Sections 12, 14, 16, 22,"),
            Cell(112, 318, "right", "IX and XIIA"),
        ]
        (row,) = schedules.rows_from_cells(cells)
        assert row["row_id"] == "2"
        assert row["not_applicable"] == [
            {"applies_to": "(4)", "provisions": "Part XII"},
            {"applies_to": "(5)", "provisions": "Sections 12, 14, 16, 22, IX and XIIA"},
        ]

    def test_an_exclusion_beside_the_row_itself_applies_to_the_row(self):
        # EA p.112: "Subsections 60(3), ..." sits beside row 1A.
        cells = [
            Cell(111, 160, "left", "1. Any person who has entered into a contract of"),
            Cell(111, 171, "left", "service."),
            Cell(111, 194, "left", "1A. Notwithstanding paragraph 1, the person whose"),
            Cell(111, 194, "right", "Subsections 60(3),"),
            Cell(111, 206, "left", "wages exceeds four thousand ringgit a month."),
            Cell(111, 206, "right", "60A(3), 60C(2A), 60D(3)"),
        ]
        rows = schedules.rows_from_cells(cells)
        assert [r["row_id"] for r in rows] == ["1", "1A"]
        assert rows[0]["not_applicable"] == []
        assert rows[1]["not_applicable"] == [
            {"applies_to": "1A", "provisions": "Subsections 60(3), 60A(3), 60C(2A), 60D(3)"}
        ]

    def test_a_number_alone_on_its_line_opens_a_row(self):
        # Sarawak p.109 puts "1." on its own line.
        cells = [Cell(109, 200, "left", "1."), Cell(109, 205, "left", "Any person, irrespective of his")]
        (row,) = schedules.rows_from_cells(cells)
        assert row["row_id"] == "1"
        assert row["content"].startswith("Any person, irrespective of his")


CONFIG = yaml.safe_load(pathlib.Path("config/config.yaml").read_text(encoding="utf-8"))


def _schedule_chunks(doc_id):
    doc = next(d for d in CONFIG["corpus"]["documents"] if d["id"] == doc_id)
    if not (pathlib.Path(CONFIG["corpus"]["raw_dir"]) / doc["file"]).exists():
        pytest.skip("source PDFs not present")
    chunks = schedules.parse_document_schedules(doc, CONFIG)
    return {c["chunk_id"]: c for c in chunks}


@pytest.mark.corpus
class TestAgainstTheRealCorpus:
    def test_ea_first_schedule_rows(self):
        chunks = _schedule_chunks("employment_act_1955")
        rows = [c for c in chunks.values() if c["chunk_type"] == "schedule_row"]
        assert [r["row_id"] for r in rows] == ["1", "1A", "2", "3"]
        two = chunks["EA1955_sch1_2"]
        assert {"applies_to": "(4)", "provisions": "Part XII"} in two["not_applicable"]
        assert "Provided that where a person is employed by one employer" in two["content"]
        assert chunks["EA1955_sch1_3"]["row_type"] == "definition"
        assert two["citation"] == "Employment Act 1955, First Schedule, para. 2"

    def test_sabah_and_sarawak_coverage_schedules_are_rows(self):
        for doc_id, prefix in (("labour_ordinance_sabah", "SBH67_sch1_"), ("labour_ordinance_sarawak", "SWK76_sch_")):
            chunks = _schedule_chunks(doc_id)
            rows = [c for c in chunks.values() if c["chunk_type"] == "schedule_row"]
            assert rows and all(r["chunk_id"].startswith(prefix) for r in rows), doc_id
            assert any(r["not_applicable"] for r in rows), doc_id

    def test_every_listed_schedule_has_a_chunk(self):
        for doc_id, expected in (
            ("employment_act_1955", {"FIRST SCHEDULE", "SECOND SCHEDULE"}),
            ("industrial_relations_act_1967", {"FIRST SCHEDULE", "SECOND SCHEDULE"}),
            ("labour_ordinance_sabah", {"FIRST SCHEDULE", "SECOND SCHEDULE", "THIRD SCHEDULE"}),
            ("labour_ordinance_sarawak", {"SCHEDULE"}),
        ):
            chunks = _schedule_chunks(doc_id)
            assert {c["section"] for c in chunks.values()} == expected, doc_id

    def test_end_matter_is_not_a_schedule(self):
        chunks = _schedule_chunks("industrial_relations_act_1967")
        assert not any("LIST OF AMENDMENTS" in c["content"] for c in chunks.values())

    def test_the_ira_essential_services_note_is_kept(self):
        chunks = _schedule_chunks("industrial_relations_act_1967")
        first = [c for c in chunks.values() if c["section"] == "FIRST SCHEDULE"]
        assert any(c["in_force_notes"] for c in first)
