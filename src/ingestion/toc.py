"""Expected-section inventory, read from each document's ARRANGEMENT OF SECTIONS.

The validator diffs the section parser's chunks against this inventory: a
section listed here with no chunk is a parser failure. The inventory is built
from the contents pages only, never from the body, so it is an independent
check on the parser rather than a restatement of its output.

The four documents lay their contents out differently, and every variant
below occurs in the real text:

* Number and title on one line (Sabah) or on two (EA, IRA, Sarawak), with
  titles that wrap and can continue across a page break.
* Ranges such as "34-36.    (Deleted)" (EA) and "19 — 33. [Deleted by AA1238]"
  (Sabah), expanded to one entry per section.
* Four placeholder spellings: "(Deleted)", "(Omitted)", "[Deleted by AA1238]"
  and "[Deleted by Act A1237.]". Placeholders are expected sections too: the
  schema keeps them as chunks so "what does section 92 say?" can answer
  "deleted" instead of abstaining.
* Running headers the extractor leaves on contents pages ("Laws of Malaysia
  ACT 177", "CAP. 76 (1948 ED.)"), dropped here.

Act A1754 has no contents pages (it is an as-passed amending Act) and is not
inventoried here; its sections are handled by amendment linking.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from src.ingestion.extract import extract_pages

_ARRANGEMENT = re.compile(r"^ARRANGEMENT OF SECTIONS$")
_HEADING = re.compile(r"^(PART|CHAPTER) ([IVXLC]+[A-Z]?|\d+)(?: [—–-] (.*))?$")
_RANGE = re.compile(r"^(\d+) ?[—–-] ?(\d+)\.(?: (.*))?$")
_ENTRY = re.compile(r"^(\d+[A-Za-z]*)\.(?: (.*))?$")
_SCHEDULE = re.compile(r"^\*?((?:FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH) )?SCHEDULE$")
_PLACEHOLDER = re.compile(r"^[\[(](Deleted|Omitted)(?: by (.+?))?\.?[\])]$")
_NOT_YET_IN_FORCE = re.compile(r"^\(NOT YET IN FORCE\) \(Section (\w+) [—–-] (\w+)\)$")
_LEADING_NUMBER = re.compile(r"^(\d+)")

# Lines that are never part of an entry: the "Section" column header, rules,
# and running headers that extract.py leaves on contents pages.
_NOISE = [
    re.compile(r"^Section$"),
    re.compile(r"^_+$"),
    re.compile(r"^\\+$"),
    re.compile(r"^\d* ?Laws of Malaysia(?: ACT \d+)?$"),
    re.compile(r"^ACT \d+$"),
    re.compile(r"^CAP\. ?\d+ \(\d{4} ED\.\)$"),
]


class TocParseError(ValueError):
    """A contents page held something the parser cannot place.

    Raised rather than skipped: a silently dropped line here is a section the
    validator will never ask for.
    """


@dataclass(frozen=True)
class TocEntry:
    """One section or schedule a document says it contains."""

    doc_id: str
    kind: str
    """"section" or "schedule"."""

    section: str
    """Upper-cased id: "60FA", "121AU", or "FIRST SCHEDULE"."""

    title: str | None
    """None for a placeholder, which carries no title."""

    part: str | None
    part_title: str | None
    chapter: str | None
    chapter_title: str | None
    status: str
    """"listed", "deleted" or "omitted"."""

    deleted_by: str | None
    """The repealing instrument when the contents names one ("AA1238")."""

    not_yet_in_force: bool
    page_index: int
    """0-based PDF page the entry starts on, for tracing a bad entry back."""


@dataclass
class _Draft:
    ids: list[str]
    kind: str
    headings: dict
    page_index: int
    not_yet_in_force: bool = False
    title_parts: list[str] | None = None


def _clean(line: str) -> str:
    return " ".join(line.split())


def _is_noise(line: str) -> bool:
    return not line or any(p.match(line) for p in _NOISE)


def _section_number(section: str) -> int:
    return int(_LEADING_NUMBER.match(section).group(1))


def _finish(draft: _Draft, doc_id: str) -> list[TocEntry]:
    title = " ".join(draft.title_parts or []) or None
    status, deleted_by = "listed", None
    if title and (placeholder := _PLACEHOLDER.match(title)):
        status, deleted_by, title = placeholder.group(1).lower(), placeholder.group(2), None
    return [
        TocEntry(
            doc_id=doc_id,
            kind=draft.kind,
            section=section,
            title=title,
            part=draft.headings["part"],
            part_title=draft.headings["part_title"],
            chapter=draft.headings["chapter"],
            chapter_title=draft.headings["chapter_title"],
            status=status,
            deleted_by=deleted_by,
            not_yet_in_force=draft.not_yet_in_force,
            page_index=draft.page_index,
        )
        for section in draft.ids
    ]


def _check(entries: list[TocEntry]) -> None:
    seen: set[str] = set()
    previous = 0
    for entry in (e for e in entries if e.kind == "section"):
        if entry.section in seen:
            raise TocParseError(f"section {entry.section} listed twice (page {entry.page_index})")
        seen.add(entry.section)
        # Only the number is order-checked. The EA puts 60FA between 60F and
        # 60G while Sabah puts 121AA after 121Z, so no letter ordering fits both.
        number = _section_number(entry.section)
        if number < previous:
            raise TocParseError(
                f"section {entry.section} follows a higher number (page {entry.page_index})"
            )
        previous = number


def parse_toc(pages: list[str], doc_id: str, first_page_index: int = 0) -> list[TocEntry]:
    """Parse the text of a document's contents pages into its inventory."""
    lines = [
        (first_page_index + offset, _clean(line))
        for offset, text in enumerate(pages)
        for line in text.splitlines()
    ]
    # Everything up to the heading is the Act's title block, not an entry.
    start = next((i + 1 for i, (_, ln) in enumerate(lines) if _ARRANGEMENT.match(ln)), 0)

    drafts: list[_Draft] = []
    # Heading titles can wrap, so they are collected line by line and joined
    # when the first entry under them is drafted.
    part = chapter = None
    part_title: list[str] = []
    chapter_title: list[str] = []
    heading_title = part_title

    def headings() -> dict:
        return {
            "part": part,
            "part_title": " ".join(part_title) or None,
            "chapter": chapter,
            "chapter_title": " ".join(chapter_title) or None,
        }
    state = None  # "heading" while reading a heading title, "entry" while reading a section title
    pending_range: tuple[str, str] | None = None
    in_range = False

    for page_index, line in lines[start:]:
        if _is_noise(line):
            continue

        if marker := _NOT_YET_IN_FORCE.match(line):
            pending_range = (marker.group(1).upper(), marker.group(2).upper())
            state = "heading"
            continue

        if heading := _HEADING.match(line):
            label = f"{heading.group(1).title()} {heading.group(2)}"
            inline = [heading.group(3)] if heading.group(3) else []
            if heading.group(1) == "PART":
                part, part_title, chapter, chapter_title = label, inline, None, []
                heading_title = part_title
            else:
                chapter, chapter_title = label, inline
                heading_title = chapter_title
            state = "heading"
            continue

        if schedule := _SCHEDULE.match(line):
            name = f"{schedule.group(1) or ''}SCHEDULE"
            drafts.append(_Draft([name], "schedule", headings(), page_index))
            state = None
            continue

        if numbered := _RANGE.match(line):
            low, high = int(numbered.group(1)), int(numbered.group(2))
            ids, rest = [str(n) for n in range(low, high + 1)], numbered.group(3)
        elif numbered := _ENTRY.match(line):
            ids, rest = [numbered.group(1).upper()], numbered.group(2)
        else:
            if state == "entry":
                if line[0].isdigit():
                    raise TocParseError(f"malformed entry {line!r} (page {page_index})")
                drafts[-1].title_parts.append(line)
            elif state == "heading":
                heading_title.append(line)
            elif state is None:
                raise TocParseError(f"unrecognised line {line!r} (page {page_index})")
            continue

        draft = _Draft(ids, "section", headings(), page_index, title_parts=[rest] if rest else [])
        if pending_range and ids[0] == pending_range[0]:
            in_range = True
        elif pending_range and not in_range:
            raise TocParseError(
                f"not-yet-in-force range should start at {pending_range[0]}, found {ids[0]}"
            )
        if in_range:
            draft.not_yet_in_force = True
            if pending_range[1] in ids:
                pending_range, in_range = None, False
        drafts.append(draft)
        state = "entry"

    if pending_range:
        raise TocParseError(f"not-yet-in-force range to {pending_range[1]} never closes")

    entries = [entry for draft in drafts for entry in _finish(draft, doc_id)]
    _check(entries)
    return entries


def inventory_for_document(doc: dict, raw_dir: str | Path) -> list[TocEntry]:
    """Extract and parse one registry document's contents pages."""
    first, last = doc["toc_pages"]
    pages = extract_pages(Path(raw_dir) / doc["file"])[first : last + 1]
    return parse_toc([p.text for p in pages], doc["id"], first_page_index=first)


def build_inventory(config_path: str | Path = "config/config.yaml") -> Path:
    """Write the inventory of every document that has contents pages."""
    config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    corpus = config["corpus"]
    out = Path(config["ingestion"]["toc_inventory_path"])
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for doc in corpus["documents"]:
            if "toc_pages" not in doc:
                continue
            for entry in inventory_for_document(doc, corpus["raw_dir"]):
                handle.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
    return out


if __name__ == "__main__":
    print(f"wrote {build_inventory()}")
