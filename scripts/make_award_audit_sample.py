"""Draw a sample of award chunks for manual checking against the PDFs (milestone A1).

    python scripts/make_award_audit_sample.py

Writes data/eval/award_audit_sample.csv (opens in Excel): 2 chunks per award, 38 in all,
seed 42, so the same chunks come out every time and the check can be reported and repeated.
Same columns as the statute audit (data/eval/chunk_audit_sample.csv). source_page is the PDF
viewer page (awards have no separate printed numbering to reconcile).
"""

from __future__ import annotations

import csv
import json
import random
from collections import defaultdict
from pathlib import Path

PER_AWARD = 2
SEED = 42
OUT = Path("data/eval/award_audit_sample.csv")


def main() -> None:
    chunks = [json.loads(line) for line in open("data/processed/award_chunks.jsonl", encoding="utf-8")]
    by_award: dict[str, list[dict]] = defaultdict(list)
    for chunk in chunks:
        by_award[chunk["doc_id"]].append(chunk)
    rng = random.Random(SEED)
    sample = [c for doc_id in sorted(by_award) for c in rng.sample(by_award[doc_id], PER_AWARD)]
    with OUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["no", "chunk_id", "citation", "case_name", "pdf_file", "open_pdf_page", "page_end",
                         "section_title", "content", "content_correct (Y/N)", "boundary_correct (Y/N)",
                         "page_correct (Y/N)", "notes"])
        for n, c in enumerate(sample, start=1):
            writer.writerow([n, c["chunk_id"], c["citation"], c["case_name"], c["source_file"], c["source_page"],
                             c["source_page_end"], c["section_title"] or "", c["content"], "", "", "", ""])
    print(f"wrote {len(sample)} rows -> {OUT}")


if __name__ == "__main__":
    main()
