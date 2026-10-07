"""Run the whole ingestion: five PDFs in, one validated chunks.jsonl out.

    python -m src.ingestion.pipeline

Steps, per registry document:
    extract.py      cleaned, page-numbered text
    toc.py          expected-section inventory (contents pages only)
    sections.py     section and subsection chunks
    schedules.py    schedule chunks
then amendments.py chunks Act A1754 and links it to Sarawak Cap. 76, and
validate.py checks the result. Output goes to data/processed/:

    chunks.jsonl            one chunk per line, every chunk with the same keys
    toc_inventory.jsonl     the expected-section inventory
    ingestion_report.json   counts, inferred titles, and any problems

Exit status is 1 if validation found problems, so this can gate CI.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

import yaml

from src.ingestion import amendments, schedules, sections, validate
from src.ingestion.extract import extract_pages
from src.ingestion.toc import inventory_for_document

_LIST_FIELDS = {"cross_references_internal", "cross_references_external", "in_force_notes",
                "amendment_annotations", "amended_by", "amends", "inserts", "target_sections",
                "not_applicable"}


def _uniform(chunks: list[dict]) -> list[dict]:
    """Give every chunk the same keys, so the store can load one schema."""
    keys: list[str] = []
    for chunk in chunks:
        keys += [k for k in chunk if k not in keys]
    return [{k: chunk.get(k, [] if k in _LIST_FIELDS else None) for k in keys} for chunk in chunks]


def run(config_path: str | Path = "config/config.yaml", out_dir: str | Path | None = None) -> dict:
    config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    raw_dir = Path(config["corpus"]["raw_dir"])
    out = Path(out_dir or config["corpus"]["processed_dir"])
    out.mkdir(parents=True, exist_ok=True)

    chunks: list[dict] = []
    inventory = []
    report: dict = {"documents": {}}
    principal_by_id: dict[str, list[dict]] = {}

    for doc in config["corpus"]["documents"]:
        if "toc_pages" not in doc:
            continue
        pages = extract_pages(raw_dir / doc["file"])
        entries = inventory_for_document(doc, raw_dir)
        doc_chunks, doc_report, schedule_lines = sections.parse_body(doc, pages, entries)
        settings = config["ingestion"]["schedules"].get(doc["id"], {})
        doc_chunks += schedules.parse_schedules(doc, pages, schedule_lines, settings, raw_dir)
        doc_report["chunks"] = len(doc_chunks)
        report["documents"][doc["id"]] = doc_report
        principal_by_id[doc["id"]] = doc_chunks
        inventory += entries
        chunks += doc_chunks

    for doc in config["corpus"]["documents"]:
        if doc.get("doc_type") != "amending":
            continue
        amending, amend_report = amendments.parse_amending_act(doc, config)
        amend_report["links"] = amendments.link(principal_by_id[doc["amends"]], amending)
        report["documents"][doc["id"]] = amend_report
        chunks += amending

    chunks = _uniform(chunks)
    problems = validate.check_coverage(inventory, chunks) + validate.check_integrity(chunks)
    for doc_id, doc_report in report["documents"].items():
        problems += [f"{doc_id}: s.{s} not found in body" for s in doc_report.get("missing", [])]
        problems += [f"{doc_id}: unresolved amendment {u}" for u in doc_report.get("links", {}).get("unresolved", [])]

    report.update(chunks=len(chunks), problems=problems)
    with (out / "chunks.jsonl").open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk, ensure_ascii=False) + "\n")
    with (out / "toc_inventory.jsonl").open("w", encoding="utf-8") as handle:
        for entry in inventory:
            handle.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
    (out / "ingestion_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    report = run()
    for doc_id, doc_report in report["documents"].items():
        print(f"{doc_id:34} {doc_report['chunks']:5} chunks")
    print(f"{'total':34} {report['chunks']:5} chunks")
    if report["problems"]:
        print(f"\n{len(report['problems'])} problem(s):")
        for problem in report["problems"]:
            print(f"  {problem}")
        return 1
    print("validation: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
