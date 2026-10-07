"""Draw a random sample of chunks for manual checking against the PDFs.

    python scripts/make_audit_sample.py

Writes data/eval/chunk_audit_sample.csv (opens in Excel). The sample is
stratified by document in proportion to its chunk count, and the seed is
fixed, so the same 60 chunks come out every time and the audit can be
reported and repeated.

Each row gives the page to open in a PDF viewer as well as the page number
printed on the statute (the chunk's source_page). They match in four of
the PDFs but not in Sarawak Cap. 76, where printed p.40 is viewer p.42.
"""

from __future__ import annotations

import csv
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ingestion.extract import extract_pages  # noqa: E402

SAMPLE_SIZE = 60
SEED = 42
CHUNKS = Path("data/processed/chunks.jsonl")
OUT = Path("data/eval/chunk_audit_sample.csv")


def _proportional(by_doc: dict[str, list], total: int) -> dict[str, int]:
    n = sum(len(v) for v in by_doc.values())
    quota = {d: max(1, round(total * len(v) / n)) for d, v in by_doc.items()}
    biggest = max(quota, key=lambda d: len(by_doc[d]))
    quota[biggest] += total - sum(quota.values())
    return quota


def main() -> None:
    config = yaml.safe_load(Path("config/config.yaml").read_text(encoding="utf-8"))
    docs = {d["id"]: d for d in config["corpus"]["documents"]}
    chunks = [json.loads(line) for line in CHUNKS.open(encoding="utf-8")]

    by_doc: dict[str, list] = defaultdict(list)
    for chunk in chunks:
        by_doc[chunk["doc_id"]].append(chunk)

    rng = random.Random(SEED)
    sample = []
    for doc_id, quota in _proportional(by_doc, SAMPLE_SIZE).items():
        sample += rng.sample(by_doc[doc_id], quota)

    viewer_page: dict[tuple[str, int], int] = {}
    for doc_id in {c["doc_id"] for c in sample}:
        for page in extract_pages(Path(config["corpus"]["raw_dir"]) / docs[doc_id]["file"]):
            if page.printed_page is not None:
                viewer_page.setdefault((doc_id, page.printed_page), page.index + 1)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig so Excel shows curly quotes and dashes correctly.
    with OUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "no", "chunk_id", "citation", "pdf_file", "open_pdf_page", "printed_page",
            "chunk_type", "status", "content",
            "content_correct (Y/N)", "boundary_correct (Y/N)", "page_correct (Y/N)", "notes",
        ])
        for n, chunk in enumerate(sample, start=1):
            writer.writerow([
                n, chunk["chunk_id"], chunk["citation"], docs[chunk["doc_id"]]["file"],
                viewer_page.get((chunk["doc_id"], chunk["source_page"]), ""), chunk["source_page"],
                chunk["chunk_type"], chunk["status"], chunk["content"], "", "", "", "",
            ])
    print(f"wrote {OUT} ({len(sample)} chunks, seed {SEED})")


if __name__ == "__main__":
    main()
