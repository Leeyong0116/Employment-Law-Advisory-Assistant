"""Tests for src/ingestion/validate.py and src/ingestion/pipeline.py."""
import json
import pathlib

import pytest
import yaml

from src.ingestion import validate
from src.ingestion.toc import TocEntry


def _entry(section, kind="section", doc_id="ea"):
    return TocEntry(doc_id, kind, section, "t", None, None, None, None, "listed", None, False, 0)


def _chunk(chunk_id, section, doc_id="ea", **extra):
    chunk = {
        "chunk_id": chunk_id, "doc_id": doc_id, "section": section, "citation": "c",
        "content": "text", "source_page": 1, "jurisdiction": "j", "status": "in_force",
        "amended_by": [], "amends": [],
    }
    chunk.update(extra)
    return chunk


class TestCoverage:
    def test_a_listed_section_without_a_chunk_is_reported(self):
        problems = validate.check_coverage([_entry("1"), _entry("2")], [_chunk("EA_s1", "1")])
        assert problems == ["ea: s.2 listed in ARRANGEMENT OF SECTIONS has no chunk"]

    def test_schedules_are_checked_too(self):
        problems = validate.check_coverage([_entry("FIRST SCHEDULE", kind="schedule")], [])
        assert problems == ["ea: FIRST SCHEDULE listed in ARRANGEMENT OF SECTIONS has no chunk"]

    def test_full_coverage_is_clean(self):
        assert validate.check_coverage([_entry("1")], [_chunk("EA_s1_1", "1"), _chunk("EA_s1_2", "1")]) == []


class TestIntegrity:
    def test_duplicate_ids(self):
        problems = validate.check_integrity([_chunk("X", "1"), _chunk("X", "2")])
        assert "duplicate chunk_id X" in problems

    def test_editorial_text_in_content(self):
        problems = validate.check_integrity([_chunk("X", "1", content="*NOTE—not yet in force")])
        assert any("editorial" in p for p in problems)

    def test_missing_citation_metadata(self):
        problems = validate.check_integrity([_chunk("X", "1", source_page=None)])
        assert any("source_page" in p for p in problems)

    def test_a_dangling_link(self):
        problems = validate.check_integrity([_chunk("X", "1", amended_by=["GONE"])])
        assert any("GONE" in p for p in problems)


CONFIG_PATH = pathlib.Path("config/config.yaml")


@pytest.mark.corpus
@pytest.mark.slow
def test_the_full_pipeline_validates_clean(tmp_path):
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    if not pathlib.Path(config["corpus"]["raw_dir"]).exists():
        pytest.skip("source PDFs not present")
    from src.ingestion import pipeline

    report = pipeline.run(CONFIG_PATH, out_dir=tmp_path)
    assert report["problems"] == []
    chunks = [json.loads(line) for line in (tmp_path / "chunks.jsonl").open(encoding="utf-8")]
    assert len(chunks) == report["chunks"]
    assert {c["doc_id"] for c in chunks} == {d["id"] for d in config["corpus"]["documents"]}
