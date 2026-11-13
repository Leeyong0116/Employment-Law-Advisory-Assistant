"""Industrial Court awards into paragraph chunks (A1, 2026-11-13).

    python -m src.ingestion.awards            parse the registry's awards, write award_chunks.jsonl
    python -m src.ingestion.awards --survey   print header fields and headings, to fill the registry

Design: docs/superpowers/specs/2026-11-13-industrial-court-awards-design.md. Plan:
docs/plans/2026-11-13-a1-award-ingestion.md.

One chunk per numbered paragraph of the court's reasoning (from the registry's
`reasoning_from` to the last paragraph), cited as "Award No. N of YYYY, para P". The
citation metadata is declared in config.yaml (`awards.documents`), hand-checked against
the PDF, and cross-checked here; it is never inferred at query time (core contribution 1).

A paragraph runs from marker k to marker k+1 only. Numbers must go up by one, so a
numbered list inside a quotation, or another award's paragraph number quoted in the text,
never splits a paragraph. Like a statute proviso, a quotation stays with its paragraph.

Output goes to a separate file, not chunks.jsonl, so the statute index cannot take in
award text before the separate award lane exists (design A-D2, milestone A3).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

MARKERS = {
    "bracket": re.compile(r"^\[(\d{1,3})\]\s*(.*)$"),
    "dot": re.compile(r"^(\d{1,3})\.(?:\s+(.*))?$"),
    "paren": re.compile(r"^\((\d{1,3})\)\s*(.*)$"),
}
SIGNATURE = re.compile(r"^(HANDED DOWN|DIBERIKAN|DATED THIS|DATED THE|Dated this)\b", re.IGNORECASE)
PAGE_NUMBER = re.compile(r"^\d{1,3}$")
PAGE_OF = re.compile(r"^Page \d+ of \d+$", re.IGNORECASE)
EDGE_DEPTH = 3  # lines at the top and bottom of a page where running headers sit
STATUTES = [
    ("Industrial Relations Act 1967", re.compile(r"Industrial Relations Act,? 1967", re.IGNORECASE)),
    ("Employment Act 1955", re.compile(r"Employment Act,? 1955", re.IGNORECASE)),
    ("Labour Ordinance (Sabah)", re.compile(r"Sabah Labour Ordinance|Labour Ordinance[^.\n]{0,25}Sabah", re.IGNORECASE)),
    ("Labour Ordinance (Sarawak)", re.compile(r"Sarawak Labour Ordinance|Labour Ordinance[^.\n]{0,25}Sarawak", re.IGNORECASE)),
]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]


@dataclass
class Paragraph:
    number: int
    text: str
    page: int                    # PDF page (1-based) where the paragraph starts
    page_end: int                # and where it ends
    heading: str | None = None   # the award's section heading in force at this paragraph


SMALL_WORDS = {"of", "the", "and", "on", "to", "in", "for", "by", "a", "an", "or", "&", "with", "into", "as", "at"}
SINGLE_WORD_HEADINGS = {"DECISION", "CONCLUSION", "REMEDY", "REMEDIES", "ISSUES", "INTRODUCTION", "PREFACE",
                        "FINDINGS", "EVALUATION", "ANALYSIS", "BACKGROUND", "SUBMISSIONS", "FACTS", "EVIDENCE"}


LABEL = re.compile(r"^\(?([A-Za-z]|[ivxIVX]{2,4}|\d{1,2})[.)]$")  # "B.", "V.", "a)", "(iv)" on their own line


def _label_text(text: str) -> bool:
    return LABEL.match(text) is not None or re.match(r"^\(?([A-Za-z]|[ivxIVX]{2,4})\)\s+\S", text) is not None


def _heading_like(line: str) -> bool:
    """Could be (part of) a heading line: starts with a capital (or is a label such as "B." or
    "a) Reinstatement"), at most 12 words, no full stop, no sentence ending. A full stop rules a
    line out, so transcript answers ("Ya. Setuju") and quoted endings stay text."""
    text = line.strip().rstrip(":").strip()
    if not text:
        return False
    if _label_text(text):
        return True
    words = text.split()
    if "." in text or text.endswith((",", ";")) or len(words) > 12 or not re.search(r"[A-Za-z]{2}", text):
        return False
    if re.match(r"^(\d|RM)", text) or " v " in f" {text} ":
        return False
    return text.lstrip("(“\"'")[:1].isupper()  # "(PREGNANCY DISCRIMINATION)" continues a heading


def is_heading(text: str) -> bool:
    """A whole heading (possibly joined from several lines): one of a few known one-word headings,
    or several words with at least one real word (not only "of", "the" ...)."""
    words = [w for w in text.split() if not LABEL.match(w)]
    if not 1 <= len(words) <= 14:
        return False
    if len(words) == 1:
        return words[0].upper().strip(":") in SINGLE_WORD_HEADINGS
    return any(len(w) >= 3 and w.lower() not in SMALL_WORDS for w in words)


def _shape(line: str) -> str:
    return re.sub(r"\d", "#", " ".join(line.split()))


def _is_marker(line: str) -> bool:
    return any(pattern.match(line.strip()) for pattern in MARKERS.values())


def clean_pages(pages: list[list[str]]) -> list[list[str]]:
    """Drop page furniture at the top and bottom of each page: bare page numbers, "Page n of m",
    and running headers (the same line shape, digits ignored, near the edge of at least half the
    pages, e.g. the case number "19/4-491/22"). Positional, as for statutes; paragraph markers
    are never furniture."""
    def edges(lines):
        filled = [line for line in lines if line.strip()]
        return filled[:EDGE_DEPTH] + filled[-EDGE_DEPTH:]

    seen: dict[str, int] = {}
    for lines in pages:
        for shape in {_shape(line) for line in edges(lines) if not _is_marker(line)}:
            seen[shape] = seen.get(shape, 0) + 1
    repeated = {shape for shape, n in seen.items() if len(pages) >= 3 and n >= max(3, len(pages) / 2)}

    def furniture(line: str) -> bool:
        stripped = line.strip()
        return (not stripped or PAGE_NUMBER.match(stripped) is not None or PAGE_OF.match(stripped) is not None
                or (_shape(stripped) in repeated and not _is_marker(stripped)))

    cleaned = []
    for lines in pages:
        lines = [line.rstrip() for line in lines]
        while lines and furniture(lines[0]):
            lines.pop(0)
        while lines and furniture(lines[-1]):
            lines.pop()
        cleaned.append(lines)
    return cleaned


def join_lines(lines: list[str]) -> str:
    """Wrapped PDF lines to running text. A blank line is a break kept inside the paragraph."""
    blocks: list[str] = []
    current = ""
    for raw in lines:
        line = " ".join(raw.split())
        if not line:
            if current:
                blocks.append(current)
                current = ""
            continue
        if current.endswith("-") and len(current) > 1 and current[-2].isalnum() and line[:1].isalnum():
            # A real hyphen at the line end ("post-" + "termination", "berturut-" + "turut"): the awards
            # are typeset from Word, which does not break words with hyphens. "are:-" keeps its space.
            current += line
        else:
            current = f"{current} {line}" if current else line
    if current:
        blocks.append(current)
    return "\n".join(blocks)


def _next(number: int, skips) -> int:
    number += 1
    while number in skips:
        number += 1
    return number


def split_paragraphs(pages: list[list[str]], numbering: str, skips=()) -> list[Paragraph]:
    """Numbered paragraphs, in order, up to the signature block. Text before [1] is the header.
    `skips`: numbers the published award leaves out (declared in the registry, hand-checked).
    Heading lines at the end of a paragraph belong to what follows: they are taken out of the
    text and become the heading of the next paragraphs."""
    skips = set(skips)
    marker = MARKERS[numbering]
    paragraphs: list[Paragraph] = []
    lines: list[str] = []
    expected, last_page, heading = _next(0, skips), 0, None

    def close() -> str | None:
        """Finish the open paragraph; return a heading found at its end, if any."""
        run = 0  # trailing heading-like lines (blank lines included) at the end of the paragraph
        while run < len(lines) and (not lines[-1 - run].strip() or _heading_like(lines[-1 - run])):
            run += 1
        found = []
        for size in range(run, 0, -1):  # the longest trailing part that is a real heading wins
            parts = [line.strip().rstrip(":").strip() for line in lines[len(lines) - size:] if line.strip()]
            candidate = " ".join(" ".join(parts).split())
            styles = {part.upper() == part for part in parts if not _label_text(part)}
            one_style = len(styles) <= 1  # "TAMIL" + "Setuju" (capitals, then not) is a transcript, not a heading
            before = next((line.strip() for line in reversed(lines[:len(lines) - size]) if line.strip()), "")
            # A heading follows a finished sentence; not "?": a question is followed by its answer.
            finished = before == "" or before.endswith((".", ":", ";", "!", "”", '"', ")", "’"))
            if parts and size < len(lines) and finished and one_style and is_heading(candidate):
                found = [candidate]
                del lines[len(lines) - size:]
                break
        if paragraphs:
            paragraphs[-1].text = join_lines(lines)
            paragraphs[-1].page_end = last_page
        return " ".join(found) or None

    for page_number, page_lines in enumerate(pages, start=1):
        for line in page_lines:
            stripped = line.strip()
            if SIGNATURE.match(stripped) and paragraphs:
                close()
                return paragraphs
            match = marker.match(stripped)
            if match and int(match.group(1)) == expected:
                heading = close() or heading
                paragraphs.append(Paragraph(expected, "", page_number, page_number, heading))
                lines = [match.group(2)] if match.group(2) else []
                expected = _next(expected, skips)
            elif paragraphs:
                lines.append(line)
            last_page = page_number if (paragraphs and stripped) else last_page
    close()
    return paragraphs


def statutes_applied(text: str) -> list[str]:
    """Statutes named anywhere in the award, in order of first mention (for the A3 region rule)."""
    text = " ".join(text.split())  # a name broken across PDF lines still counts
    found = [(m.start(), name) for name, pattern in STATUTES if (m := pattern.search(text))]
    return [name for _, name in sorted(found)]


def _long_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def reasoning_ranges(meta: dict) -> list[tuple[int, int]]:
    """The court's reasoning as inclusive paragraph ranges: `reasoning: [[from, to], ...]` from the
    registry (hand-checked), or `reasoning_from` meaning from there to the end."""
    if meta.get("reasoning"):
        return [(int(a), int(b)) for a, b in meta["reasoning"]]
    return [(int(meta["reasoning_from"]), 10**6)]


def award_chunks(meta: dict, paragraphs: list[Paragraph], statutes: list[str]) -> list[dict]:
    """Chunks for the reasoning paragraphs (design A-D1), citation fields from the registry."""
    ranges = reasoning_ranges(meta)
    number, year = re.match(r"(\d+) of (\d{4})", meta["award_number"]).groups()
    doc_id = f"ICA{year}_{number}"
    return [
        {
            "chunk_id": f"{doc_id}_p{p.number}",
            "doc_id": doc_id,
            "doc_type": "award",
            "chunk_type": "award_paragraph",
            "statute": f"Industrial Court Award No. {meta['award_number']}",
            "citation": f"Award No. {meta['award_number']}, para {p.number}",
            "case_name": meta["case_name"],
            "case_number": meta["case_number"],
            "award_number": meta["award_number"],
            "award_date": meta["award_date"],
            "chairman": meta["chairman"],
            "venue": meta["venue"],
            "paragraph": p.number,
            "section": None,
            "section_title": p.heading,
            "content": p.text,
            "statutes_applied": statutes,
            "cross_references_internal": [],
            "cross_references_external": [],
            "jurisdiction": "Malaysia",
            "status": "in_force",
            "source_version": f"handed down {_long_date(meta['award_date'])}",
            "source_page": p.page,
            "source_page_end": p.page_end,
            "source_url": meta.get("source_url"),
            "source_file": meta["file"],
        }
        for p in paragraphs
        if any(a <= p.number <= b for a, b in ranges)
    ]


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).upper()


def validate_award(meta: dict, paragraphs: list[Paragraph], text: str) -> list[str]:
    """Problems for one award; an empty list means clean."""
    name, problems = meta["award_number"], []
    number, year = re.match(r"(\d+) of (\d{4})", meta["award_number"]).groups()
    if not re.search(rf"\b{number}\s*(OF(\s*YEAR)?|TAHUN|/)\s*{year}\b", _flat(text)):
        problems.append(f"{name}: award number {meta['award_number']} not found in the text")
    if meta["case_number"].replace(" ", "").upper() not in _flat(text).replace(" ", ""):
        problems.append(f"{name}: case number {meta['case_number']} not found in the text")
    skips, marker = set(meta.get("skips") or []), MARKERS[meta["numbering"]]
    numbers = [p.number for p in paragraphs]
    expected = [n for n in range(1, (numbers[-1] if numbers else 0) + 1) if n not in skips]
    if numbers != expected:
        problems.append(f"{name}: paragraphs not consecutive: {numbers[:5]}...")
    if numbers:
        later = [int(m.group(1)) for line in text.splitlines() if (m := marker.match(line.strip()))
                 and numbers[-1] < int(m.group(1)) <= numbers[-1] + 5 and int(m.group(1)) not in skips]
        if later:
            problems.append(f"{name}: numbering stops after para {numbers[-1]} (marker {later[0]} found later): "
                            "declare the missing numbers in `skips` after checking the PDF")
    last = numbers[-1] if numbers else 0
    ranges = reasoning_ranges(meta)
    for a, b in ranges:
        if meta.get("reasoning") and not (1 <= a <= b <= last):
            problems.append(f"{name}: reasoning range [{a}, {b}] outside 1..{last}")
        elif not meta.get("reasoning") and not 1 <= a <= last:
            problems.append(f"{name}: reasoning_from {a} outside 1..{last}")
    kept = [p for p in paragraphs if any(a <= p.number <= b for a, b in ranges)]
    if len(kept) < meta.get("min_reasoning", 5):
        problems.append(f"{name}: only {len(kept)} reasoning paragraphs")
    problems += [f"{name}: para {p.number} is empty" for p in paragraphs if not p.text.strip()]
    problems += [f"{name}: para {p.number} contains signature text" for p in paragraphs if SIGNATURE.search(p.text)]
    return problems


def read_pdf(path: Path) -> list[list[str]]:
    import pymupdf

    with pymupdf.open(path) as document:
        return [page.get_text().splitlines() for page in document]


def run(config_path: str | Path = "config/config.yaml") -> dict:
    config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    settings = config["awards"]
    raw_dir, out = Path(settings["raw_dir"]), Path(config["corpus"]["processed_dir"])
    chunks, report = [], {"awards": {}, "problems": []}
    for meta in settings["documents"]:
        pages = read_pdf(raw_dir / meta["file"])
        text = "\n".join(line for page in pages for line in page)
        paragraphs = split_paragraphs(clean_pages(pages), meta["numbering"], meta.get("skips") or [])
        statutes = statutes_applied(text)
        problems = validate_award({"min_reasoning": settings.get("min_reasoning", 5), **meta}, paragraphs, text)
        award = award_chunks(meta, paragraphs, statutes)
        report["awards"][meta["award_number"]] = {"paragraphs": len(paragraphs), "reasoning_kept": len(award),
                                                  "statutes_applied": statutes, "problems": problems}
        report["problems"] += problems
        chunks += award
    ids = [c["chunk_id"] for c in chunks]
    report["problems"] += [f"duplicate chunk_id {i}" for i in sorted({i for i in ids if ids.count(i) > 1})]
    report["chunks"] = len(chunks)
    with (out / "award_chunks.jsonl").open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk, ensure_ascii=False) + "\n")
    (out / "award_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


HEADING = re.compile(r"^[A-Z][A-Za-z’'&()\- ]{2,60}:?$")


def survey(raw_dir: Path) -> None:
    """Print, per PDF: header lines, the numbering style that fits, and each heading with the
    paragraph number after it. A reading aid for filling the registry, not used by run()."""
    for path in sorted(raw_dir.glob("*.pdf")):
        pages = read_pdf(path)
        flat = [line.strip() for page in clean_pages(pages) for line in page if line.strip()]
        counts = {style: len(split_paragraphs(clean_pages(pages), style)) for style in MARKERS}
        style = max(counts, key=counts.get)
        print(f"\n===== {path.name}  numbering {counts}")
        print("  header:", " | ".join(flat[:22]))
        marker, last = MARKERS[style], 0
        for i, line in enumerate(flat):
            m = marker.match(line)
            if m and int(m.group(1)) == last + 1:
                last += 1
            elif HEADING.match(line) and not line.isdigit() and len(line.split()) <= 8:
                print(f"  before para {last + 1:3d}: {line}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--survey", action="store_true")
    args = parser.parse_args()
    if args.survey:
        config = yaml.safe_load(Path("config/config.yaml").read_text(encoding="utf-8"))
        survey(Path((config.get("awards") or {}).get("raw_dir", "data/raw/court case")))
        return 0
    report = run()
    for number, info in report["awards"].items():
        print(f"Award {number:13s} paragraphs {info['paragraphs']:4d}  reasoning kept {info['reasoning_kept']:4d}  "
              f"{', '.join(info['statutes_applied'])}")
    print(f"total {report['chunks']} chunks")
    if report["problems"]:
        print(f"\n{len(report['problems'])} problem(s):")
        for problem in report["problems"]:
            print(f"  {problem}")
        return 1
    print("validation: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
