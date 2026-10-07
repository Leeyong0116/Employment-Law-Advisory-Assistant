"""Schedule parser: the material after the last section.

Two kinds of schedule occur in the corpus.

Coverage tables ("Employee" / "Provision of the Act not applicable") in the
EA, Sabah and Sarawak. These decide who is excluded from what, e.g. who is
outside the overtime rules, so they are parsed from word coordinates: the
two columns interleave in plain text. One chunk per top-level numbered row,
with nested sub-items kept inside it (schema decision, docs/chunk_schema.md).
Each exclusion is kept with the sub-item it is printed level with: in the EA
"Part XII" sits beside item (4) (seamen) and the long section list beside
item (5) (domestic employees). Merging the right column into one blob would
claim every exclusion applies to the whole row, which the source does not
say. The alignment is recorded as printed; no legal reading is applied.

Everything else (IRA essential services, Sabah hazardous work lists, the EA
repealed-laws table) is chunked as plain text.

The EA and IRA end with LIST OF AMENDMENTS tables. They are provenance, not
schedules, and are out of M1 scope (docs/chunk_schema.md).
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from src.ingestion.extract import Page, extract_pages
from src.ingestion.sections import BodyLine, join_lines, parse_body
from src.ingestion.toc import inventory_for_document

_HEADING = re.compile(r"^\s*\*?((?:FIRST|SECOND|THIRD|FOURTH|FIFTH) )?SCHEDULE\s*$")
# Sarawak prints "LIST  OF  AMENDMENTS" with double spaces.
_END_MATTER = re.compile(r"^\s*LIST\s+OF\s+(?:AMENDMENTS|SECTIONS\s+AMENDED)\s*$")
_ROW = re.compile(r"^\s*(\d+[A-Z]?)\.(?:\s+(.*))?$")
_NESTED = re.compile(r"^\s*\((\d+|[a-z]{1,2})\)")
_REFERENCE = re.compile(r"^\s*\[(?:Sub)?[Ss]ection.*\]\s*$")
_COLUMN_HEADER = re.compile(
    r"^\s*(?:Employee|applicable|Not Applicable|Provision of the (?:Act|Ordinance)\b.*)\s*$"
)
_BARE_COLUMN_NUMBER = re.compile(r"^\s*\(\d\)\s*$")
_DEFINES = re.compile(r'[“"][^”"]{1,60}[”"]\s*means\b')

_ORDINALS = {"FIRST": "1", "SECOND": "2", "THIRD": "3", "FOURTH": "4", "FIFTH": "5"}
_MAX_WORDS = 450


@dataclass(frozen=True)
class Cell:
    """One line of text in one column of a schedule table."""

    page_index: int
    y: float
    column: str
    """"left" or "right"."""

    text: str


_TITLE_BLOCK = re.compile(r"^(?:[^a-z]*[A-Z][^a-z]*|Act \w+|Chapter\s+\d+(?:\s+\(\d{4}\s+Ed\.\))?)$")


def _is_title_line(text: str) -> bool:
    """A line of the title block that heads the amendment list."""
    text = " ".join(text.split())
    return bool(_TITLE_BLOCK.match(text)) and not _HEADING.match(text) and not text.endswith((".", ",", ";"))


def split_schedules(lines: list[BodyLine]) -> list[tuple[str, list[BodyLine]]]:
    """Split the post-section lines into (name, lines), stopping at end matter."""
    return [(name, part) for name, part, _ in _split_with_stops(lines)]


def _split_with_stops(
    lines: list[BodyLine],
) -> list[tuple[str, list[BodyLine], BodyLine | None]]:
    """As split_schedules, plus the first line after each schedule.

    The stop line bounds the coordinate reader, which sees whole pages: the
    Sarawak Schedule shares its last page with the LIST OF AMENDMENTS.
    """
    end = len(lines)
    for number, line in enumerate(lines):
        if _END_MATTER.match(line.text):
            # A title block heads the list: "LAWS OF MALAYSIA" / "Act 177" /
            # "<TITLE>" in the EA and IRA, "LABOUR ORDINANCE" / "Chapter 76" /
            # "(1958 Ed.)" in Sarawak. Step back over short lines that do not
            # start lower-case, never into statute text ("payment.").
            end = number
            while end > 0 and number - end < 4 and _is_title_line(lines[end - 1].text):
                end -= 1
            break

    parts: list[tuple[str, list[BodyLine], BodyLine | None]] = []
    for line in lines[:end]:
        if match := _HEADING.match(line.text):
            if parts:
                parts[-1] = (parts[-1][0], parts[-1][1], line)
            parts.append((f"{match.group(1) or ''}SCHEDULE", [], None))
        elif parts:
            parts[-1][1].append(line)
    if parts and end < len(lines):
        parts[-1] = (parts[-1][0], parts[-1][1], lines[end])
    return parts


# A right-hand block can sit a few points above the left line it belongs to
# (Sabah First Schedule: block at y 283.8, row 2 at y 286.4).
_ALIGN_TOLERANCE = 6.0
_BLOCK_GAP = 20.0


def rows_from_cells(cells: list[Cell]) -> list[dict]:
    """Group table cells into rows, keeping each exclusion with its sub-item.

    Left cells build the rows and a timeline of anchors (the row itself, or
    its current top-level sub-item). Consecutive right cells form a block,
    which goes to the anchor in force at the block's top line.
    """
    rows: list[dict] = []
    anchors: list[tuple[int, float, int, str]] = []
    nested_kind: str | None = None
    ordered = sorted(cells, key=lambda c: (c.page_index, c.y))

    for cell in (c for c in ordered if c.column == "left"):
        text = " ".join(cell.text.split())
        if match := _ROW.match(text):
            rows.append({"row_id": match.group(1), "lines": [], "na": [], "pages": set()})
            anchors.append((cell.page_index, cell.y, len(rows) - 1, match.group(1)))
            nested_kind = None
            text = match.group(2) or ""
        elif not rows:
            continue
        elif nested := _NESTED.match(text):
            # The first nested marker in a row fixes the level that can carry
            # an exclusion: "(1)" to "(5)" in the EA, "(a)" in Sabah/Sarawak.
            kind = "digit" if nested.group(1).isdigit() else "alpha"
            nested_kind = nested_kind or kind
            if kind == nested_kind:
                anchors.append((cell.page_index, cell.y, len(rows) - 1, f"({nested.group(1)})"))
        if text:
            rows[-1]["lines"].append(text)
        rows[-1]["pages"].add(cell.page_index)

    blocks: list[list[Cell]] = []
    for cell in (c for c in ordered if c.column == "right"):
        last = blocks[-1][-1] if blocks else None
        if last and last.page_index == cell.page_index and cell.y - last.y < _BLOCK_GAP:
            blocks[-1].append(cell)
        else:
            blocks.append([cell])

    for block in blocks:
        top = (block[0].page_index, block[0].y + _ALIGN_TOLERANCE)
        owner = [a for a in anchors if (a[0], a[1]) <= top]
        if not owner:
            continue
        _, _, row_index, anchor = owner[-1]
        row = rows[row_index]
        text = " ".join(" ".join(c.text.split()) for c in block)
        if row["na"] and row["na"][-1][0] == anchor:
            row["na"][-1][1].append(text)
        else:
            row["na"].append((anchor, [text]))
        row["pages"].add(block[0].page_index)

    return [
        {
            "row_id": row["row_id"],
            "content": join_lines(row["lines"]),
            "not_applicable": [
                {"applies_to": target, "provisions": " ".join(texts)} for target, texts in row["na"]
            ],
            "pages": sorted(row["pages"]),
        }
        for row in rows
    ]


def _heading_y(page: pymupdf.Page, text: str) -> float | None:
    """y of the first line on the page reading exactly `text`."""
    wanted = " ".join(text.replace("*", "").split())
    for line in _word_lines(page):
        if " ".join(line[2].replace("*", "").split()) == wanted:
            return line[0]
    return None


def _word_lines(page: pymupdf.Page, split_x: float | None = None):
    """(y, x, text, column) for each text line, split into columns if asked."""
    grouped: dict[tuple, list] = defaultdict(list)
    for word in page.get_text("words"):
        column = "right" if split_x is not None and word[0] >= split_x else "left"
        grouped[(word[5], word[6], column)].append(word)
    lines = []
    for (_, _, column), words in grouped.items():
        words.sort(key=lambda w: w[0])
        lines.append((min(w[1] for w in words), words[0][0], " ".join(w[4] for w in words), column))
    return sorted(lines)


def cells_from_pdf(
    pdf: pymupdf.Document,
    pages: list[Page],
    page_indexes: list[int],
    name: str,
    stop: BodyLine | None,
    split_x: float,
) -> list[Cell]:
    """Read a two-column schedule's cells, dropping headers and furniture."""
    cells: list[Cell] = []
    first, last = page_indexes[0], page_indexes[-1]
    if stop is not None and stop.page_index > last:
        stop = None
    for index in range(first, last + 1):
        page = pdf[index]
        furniture = [" ".join(f.split()) for f in pages[index].furniture]
        y_start = _heading_y(page, name) if index == first else None
        y_stop = _heading_y(page, stop.text) if stop is not None and index == last else None
        lines = _word_lines(page, split_x)
        header_ys = [y for y, _, text, _ in lines if _COLUMN_HEADER.match(text)]
        for y, _, text, column in lines:
            clean = " ".join(text.split())
            if (y_start is not None and y <= y_start) or (y_stop is not None and y >= y_stop):
                continue
            if _HEADING.match(clean) or _REFERENCE.match(clean) or _COLUMN_HEADER.match(clean):
                continue
            if _BARE_COLUMN_NUMBER.match(clean) and any(abs(y - h) < 25 for h in header_ys):
                continue
            if len(clean) >= 2 and any(clean in f for f in furniture):
                continue
            cells.append(Cell(index, y, column, clean))
    return cells


def _schedule_key(name: str) -> str:
    ordinal = name.split()[0] if " " in name else ""
    return f"sch{_ORDINALS.get(ordinal, '')}"


def _title(name: str) -> str:
    return " ".join(word.capitalize() for word in name.split())


def _base_chunk(doc: dict, name: str, chunk_id: str, citation: str, content: str, pages: list[Page], page_indexes: list[int]) -> dict:
    printed = [pages[i].printed_page for i in page_indexes if pages[i].printed_page is not None]
    return {
        "chunk_id": chunk_id,
        "doc_id": doc["id"],
        "statute": doc["short_name"],
        "act_number": doc["act_number"],
        "part": None,
        "part_title": None,
        "chapter": None,
        "chapter_title": None,
        "section": name,
        "section_title": None,
        "subsection": None,
        "citation": citation,
        "chunk_type": "schedule",
        "defined_term": None,
        "definition_scope": None,
        "content": content,
        "status": "in_force",
        "deleted_by": None,
        "cross_references_internal": [],
        "cross_references_external": [],
        "in_force_notes": [],
        "amendment_annotations": [],
        "jurisdiction": doc["jurisdiction_label"],
        "source_version": doc["source_version"],
        "as_at": str(doc["as_at"]),
        "source_page": printed[0] if printed else None,
        "source_page_end": printed[-1] if printed else None,
        "source_url": doc.get("source_url"),
        "parse_rule": "schedule_text",
        "_page_indexes": page_indexes,
    }


def _text_chunks(doc: dict, name: str, lines: list[BodyLine], pages: list[Page]) -> list[dict]:
    """Plain schedules: one chunk, or word-bounded parts at numbered items."""
    reference = next((ln.text.strip() for ln in lines[:3] if _REFERENCE.match(ln.text)), None)
    title_lines: list[str] = []
    skip = 0
    for line in lines[:4]:
        text = line.text.strip()
        if _REFERENCE.match(text):
            skip += 1
        elif text.isupper() and not re.match(r"^[A-Z]\.\s", text) and not _ROW.match(text):
            title_lines.append(text)
            skip += 1
        else:
            break
    body = lines[skip:]

    groups: list[list[BodyLine]] = [[]]
    words = 0
    for line in body:
        n = len(line.text.split())
        if groups[-1] and words + n > _MAX_WORDS and (_ROW.match(line.text) or words + n > _MAX_WORDS * 1.3):
            groups.append([])
            words = 0
        groups[-1].append(line)
        words += n

    chunks = []
    key = _schedule_key(name)
    for k, group in enumerate(groups, start=1):
        suffix = f"_p{k}" if len(groups) > 1 else ""
        chunk = _base_chunk(
            doc, name, f"{doc['chunk_prefix']}_{key}{suffix}",
            f"{doc['short_name']}, {_title(name)}" + (f" (part {k})" if len(groups) > 1 else ""),
            join_lines([ln.text for ln in group]), pages,
            sorted({ln.page_index for ln in group}),
        )
        chunk["section_title"] = " ".join(title_lines) or None
        chunk["schedule_reference"] = reference
        chunks.append(chunk)
    return chunks


def _row_chunks(doc: dict, name: str, rows: list[dict], pages: list[Page], reference: str | None) -> list[dict]:
    instrument = "Ordinance" if "Ordinance" in doc["short_name"] else "Act"
    label = f"Provisions of the {instrument} not applicable"
    key = _schedule_key(name)
    chunks = []
    for row in rows:
        lines = [row["content"]]
        for item in row["not_applicable"]:
            target = "" if item["applies_to"] == row["row_id"] else f" to {item['applies_to']}"
            lines.append(f"{label}{target}: {item['provisions']}")
        chunk = _base_chunk(
            doc, name, f"{doc['chunk_prefix']}_{key}_{row['row_id']}",
            f"{doc['short_name']}, {_title(name)}, para. {row['row_id']}",
            "\n".join(lines), pages, row["pages"],
        )
        chunk.update(
            chunk_type="schedule_row",
            row_type="definition" if _DEFINES.search(row["content"]) else "exemption",
            row_id=row["row_id"],
            not_applicable=row["not_applicable"],
            schedule_reference=reference,
            parse_rule="schedule_row",
        )
        chunks.append(chunk)
    return chunks


def _attach_notes(chunks: list[dict], pages: list[Page]) -> None:
    for chunk in chunks:
        for index in chunk["_page_indexes"][:1]:
            chunk["in_force_notes"].extend(pages[index].footnotes)
    for chunk in chunks:
        del chunk["_page_indexes"]


def parse_schedules(
    doc: dict, pages: list[Page], lines: list[BodyLine], settings: dict, raw_dir: str | Path
) -> list[dict]:
    """Chunk every schedule of one document."""
    parts = _split_with_stops(lines)
    two_column = set(settings.get("two_column", []))
    chunks: list[dict] = []
    with pymupdf.open(Path(raw_dir) / doc["file"]) as pdf:
        for name, part_lines, stop in parts:
            if not part_lines:
                continue
            if name in two_column:
                page_indexes = sorted({ln.page_index for ln in part_lines})
                cells = cells_from_pdf(pdf, pages, page_indexes, name, stop, settings["column_split_x"])
                reference = next((ln.text.strip() for ln in part_lines[:3] if _REFERENCE.match(ln.text)), None)
                chunks += _row_chunks(doc, name, rows_from_cells(cells), pages, reference)
            else:
                chunks += _text_chunks(doc, name, part_lines, pages)
    seen: set[int] = set()
    for chunk in chunks:
        # A page's notes go to the first chunk on that page only.
        chunk["_page_indexes"] = [i for i in chunk["_page_indexes"] if i not in seen] or [-1]
        seen.update(chunk["_page_indexes"])
    _attach_notes(chunks, pages + [Page(-1, None, "")])
    return chunks


def parse_document_schedules(doc: dict, config: dict) -> list[dict]:
    """Extract one document and chunk its schedules (used by tests and tools)."""
    raw_dir = config["corpus"]["raw_dir"]
    pages = extract_pages(Path(raw_dir) / doc["file"])
    _, _, lines = parse_body(doc, pages, inventory_for_document(doc, raw_dir))
    settings = config["ingestion"]["schedules"].get(doc["id"], {})
    return parse_schedules(doc, pages, lines, settings, raw_dir)
