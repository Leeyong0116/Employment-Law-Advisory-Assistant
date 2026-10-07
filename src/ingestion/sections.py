"""Section parser: cleaned pages to citation-ready chunks.

The chunk boundary is the subsection, the smallest complete legal rule. A
short undivided section is one chunk. Provisos are never a boundary: a chunk
that loses its proviso still reads fluently and cites correctly, but is wrong.

The parser walks the body guided by the toc.py inventory. Every section the
contents list is searched for, in order, at the start of a line; a section
whose start cannot be found is reported missing, never guessed. This copes
with every numbering layout in the corpus without a per-document rule:

    EA, IRA     "5. (1) No employer ..."      title on the line above
    Sabah       "10." / "(1)" / text          title above, ending in "."
                "Section 14. [Deleted by AA1238]"
    Sarawak     "2.—(1)" / text               title above
    EA ranges   "34-36.   (Deleted by Act A1651)."

Editorial material never reaches a chunk's content: page footnotes become
in_force_notes, and Sarawak's "[Am. Act A1237.]" tags become
amendment_annotations.

Interpretation subsections are split into one definition chunk per term.
Section 2(1) of the EA holds dozens of definitions, and as a single chunk
any one of them would be diluted past retrieval.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass
from pathlib import Path

from src.ingestion.extract import Page, extract_pages
from src.ingestion.toc import TocEntry, inventory_for_document


@dataclass(frozen=True)
class BodyLine:
    page_index: int
    printed_page: int | None
    text: str


# Footnote markers can prefix the number ("**9. (1)" in the IRA).
_LINE_START = re.compile(r"^\s*\*{0,3}(?:Section\s+)?(\d+[A-Za-z]*)\.(?=[\s—–-]|$)")
# "34-36." (EA) or "Section 75 — 82" with no full stop (Sabah).
_RANGE_START = re.compile(
    r"^\s*\*{0,3}(?:Section\s+(\d+)\s*[-—–]\s*(\d+)\.?|(\d+)\s*[-—–]\s*(\d+)\.)(?=\s|$)"
)
_RULE_LINE = re.compile(r"^\s*(?:_{5,}|[\[\]])\s*$")
_HEADING = re.compile(r"^\s*(?:PART|CHAPTER)\s+(?:[IVXLC]+[A-Z]?|\d+)\b")
_SCHEDULE_HEADING = re.compile(r"^\s*\*?(?:(?:FIRST|SECOND|THIRD|FOURTH|FIFTH) )?SCHEDULE\s*$")
_END_MATTER = re.compile(r"^\s*LIST\s+OF\s+(?:AMENDMENTS|SECTIONS\s+AMENDED)\s*$")
_SUBSECTION = re.compile(r"^\s*\((\d+)([A-Z]{0,2})\)\s*")
_PARAGRAPH = re.compile(r"^\s*(?:\((?:[a-z]{1,3}|[ivxl]+|[A-Z])\)|Provided\b)")
_DEFINITION = re.compile(r'^\s*[“"]([^”"]{1,80})[”"]')
_INLINE_DEFINITION = re.compile(
    r'[“"]([^”"]{1,80})[”"]\s*(?:,[^,;]{0,60},\s*)?(?:means|includes)\b'
)
_DEFINES = re.compile(r"\b(?:means|includes|has the (?:same )?meaning|shall have the)\b")
_PLACEHOLDER = re.compile(
    r"^[\[(](Deleted|Omitted|Repealed)(?: by)?(?: (.+?))?\.?[\])]\.?$", re.IGNORECASE
)
_ANNOTATION = re.compile(r"^\s*\[(?:Am|Sub|Ins|Mod|Added)\.\s[^\]]*\]\.?\s*$")
_ASTERISK = re.compile(r"\*+(?=[\w(])")
_WORD = re.compile(r"[a-z0-9]+")

_INTERNAL_REF = re.compile(
    r"\b(?:sub)?sections?\s+((?:\d+[A-Z]*(?:\(\d+[A-Z]?\))?)(?:\s*(?:,|and|or|to)\s*\d+[A-Z]*(?:\(\d+[A-Z]?\))?)*)"
)
_OTHER_STATUTE_AFTER = re.compile(r"^[^.;]{0,40}?\bof the [A-Z][\w’' ]*(?:Act|Ordinance|Enactment)\b")
_EXTERNAL_REF = re.compile(
    r"\b((?:[A-Z][\w’'()]*\s+)+(?:Act|Ordinance|Enactment|Order|Regulations)\s+\d{4}(?:\s*\[(?:Act|Cap\.)\s*[\w.]+\])?)"
)


# --------------------------------------------------------------------------
# Text helpers
# --------------------------------------------------------------------------


def join_lines(lines: list[str]) -> str:
    """Join PDF lines into readable text.

    Wrapped prose is joined with spaces. Paragraph markers such as "(a)" and
    "Provided" start a new line, unless the marker stands alone on its line,
    in which case its text follows on the next line.
    """
    out: list[str] = []
    for raw in lines:
        line = " ".join(_ASTERISK.sub("", raw).split())
        if not line:
            continue
        starts_block = _PARAGRAPH.match(line) or _DEFINITION.match(line)
        if not out:
            out.append(line)
        elif out[-1].endswith("-") and out[-1][-2:-1].isalpha():
            out[-1] += line
        elif starts_block and not _is_bare_marker(out[-1]):
            out.append(line)
        else:
            out[-1] += " " + line
    return "\n".join(out)


def _is_bare_marker(line: str) -> bool:
    return bool(re.fullmatch(r"\((?:[a-z]{1,3}|[ivxl]+|[A-Z]|\d+[A-Z]?)\)", line.strip()))


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _title_score(expected: str, candidate: str) -> float:
    """Dice overlap of word sets: tolerant of Sabah's reworded titles."""
    a, b = set(_words(expected)), set(_words(candidate))
    if not a or not b:
        return 0.0
    return 2 * len(a & b) / (len(a) + len(b))


def parse_placeholder(text: str) -> tuple[str, str | None] | None:
    """Return (status, instrument) for a deleted/omitted placeholder, else None."""
    match = _PLACEHOLDER.match(" ".join(_ASTERISK.sub("", text).split()))
    if not match:
        return None
    status = "omitted" if match.group(1).lower() == "omitted" else "deleted"
    return status, match.group(2)


def lift_annotations(lines: list[BodyLine]) -> tuple[list[BodyLine], list[str]]:
    """Separate Sarawak amendment tags ("[Am. Act A1237.]") from statute text."""
    kept, tags = [], []
    for line in lines:
        if _ANNOTATION.match(line.text):
            tags.append(" ".join(line.text.split()))
        else:
            kept.append(line)
    return kept, tags


def _successor(current: tuple[int, str], candidate: tuple[int, str]) -> bool:
    number, suffix = current
    cand_number, cand_suffix = candidate
    if cand_number == number + 1:
        return cand_suffix in ("", "A")
    if cand_number == number:
        return len(cand_suffix) >= len(suffix) and cand_suffix > suffix
    return False


def _closes(lines: list[BodyLine]) -> bool:
    """Whether a subsection's text so far ends where a new one may begin.

    Rejects a wrapped reference: "under subsection" / "(3) of section 18;"
    puts "(3)" at the start of a line, but the line above ends mid-phrase.
    """
    last = next((ln.text.strip() for ln in reversed(lines) if ln.text.strip()), "")
    return not last or bool(re.search(r"[.;:—\])]$", last)) or _is_bare_marker(last)


def split_subsections(lines: list[BodyLine]) -> list[tuple[str | None, list[BodyLine]]]:
    """Split a section body at its subsection markers.

    Only the next expected marker at the start of a line opens a subsection,
    so a wrapped reference such as "subsection" / "(1) of section 3" cannot
    cause a false split. A body that does not open with "(1)" is undivided.
    """
    first = _SUBSECTION.match(lines[0].text) if lines else None
    if not first or first.group(1) != "1":
        return [(None, lines)]

    parts: list[tuple[str | None, list[BodyLine]]] = []
    current: tuple[int, str] | None = None
    for line in lines:
        match = _SUBSECTION.match(line.text)
        key = (int(match.group(1)), match.group(2)) if match else None
        if key and (current is None or (_successor(current, key) and _closes(parts[-1][1]))):
            current = key
            rest = line.text[match.end():]
            parts.append((f"({key[0]}{key[1]})", [BodyLine(line.page_index, line.printed_page, rest)]))
        else:
            parts[-1][1].append(line)
    return parts


def split_definitions(lines: list[BodyLine]) -> tuple[str | None, list[tuple[str, list[BodyLine]]]]:
    """Split an interpretation provision into (scope, [(term, lines)]).

    A definition starts at a line opening with a quoted term that "means",
    "includes" or "has the meaning" within the next line or so. The text
    before the first definition ("In this Act, unless the context otherwise
    requires—") is returned as the scope, which matters legally: "In this
    Part" and "In this Act" define over different ranges.
    """
    starts: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        match = _DEFINITION.match(line.text)
        if not match:
            continue
        window = line.text[match.end():] + " " + (lines[index + 1].text if index + 1 < len(lines) else "")
        if _DEFINES.search(window[:160]) and not re.match(r"\s*shall be construed", window):
            starts.append((index, " ".join(match.group(1).split())))
    if not starts:
        # A subsection can define a term mid-sentence: Sarawak s.84(11) "For
        # the purposes of this section, “children” means ...". The whole
        # subsection is then the definition, so it is still co-retrieved.
        text = " ".join(ln.text for ln in lines)
        if (inline := _INLINE_DEFINITION.search(text)) and text.count("“") + text.count('"') <= 4:
            return None, [(" ".join(inline.group(1).split()), lines)]
        return None, []

    scope = join_lines([ln.text for ln in lines[: starts[0][0]]]) or None
    bounds = [i for i, _ in starts] + [len(lines)]
    definitions = [(term, lines[bounds[k] : bounds[k + 1]]) for k, (_, term) in enumerate(starts)]
    return scope, definitions


def internal_references(text: str, known: set[str]) -> list[str]:
    """Section references that resolve inside this document, as "s. 29(2)"."""
    found: list[str] = []
    for match in _INTERNAL_REF.finditer(text):
        if _OTHER_STATUTE_AFTER.match(text[match.end():]):
            continue
        for ref in re.findall(r"\d+[A-Z]*(?:\(\d+[A-Z]?\))?", match.group(1)):
            section = re.match(r"\d+[A-Z]*", ref).group(0)
            if section in known and f"s. {ref}" not in found:
                found.append(f"s. {ref}")
    return found


def external_references(text: str, own: str) -> list[str]:
    """Statutes outside this document, so an answer can flag the dependency."""
    found: list[str] = []
    for match in _EXTERNAL_REF.finditer(" ".join(text.split())):
        name = re.sub(r"^(?:the|The|of|under|in)\s+", "", match.group(1)).strip()
        if own.lower() in name.lower() or name in found:
            continue
        found.append(name)
    return found


# --------------------------------------------------------------------------
# Locating sections in the body
# --------------------------------------------------------------------------


@dataclass
class _Located:
    entries: list[TocEntry]
    start: int
    header_start: int = 0
    body_title: str | None = None
    title_matched: bool = False
    title_inferred: bool = False


def body_lines(pages: list[Page], first_body_page: int) -> list[BodyLine]:
    return [
        BodyLine(page.index, page.printed_page, line)
        for page in pages[first_body_page:]
        for line in page.text.splitlines()
        if line.strip() and not _RULE_LINE.match(line)
    ]


def _start_index(lines: list[BodyLine]) -> dict[str, list[int]]:
    """Map each section id to the line numbers where it could start."""
    index: dict[str, list[int]] = {}
    for number, line in enumerate(lines):
        if bounds := _range_bounds(line.text):
            for n in range(bounds[0], bounds[1] + 1):
                index.setdefault(str(n), []).append(number)
        elif match := _LINE_START.match(line.text):
            index.setdefault(match.group(1).upper(), []).append(number)
    return index


def _number(section: str) -> int:
    return int(re.match(r"\d+", section).group(0))


def _range_bounds(text: str) -> tuple[int, int] | None:
    match = _RANGE_START.match(text)
    if not match:
        return None
    low, high = (match.group(1), match.group(2)) if match.group(1) else (match.group(3), match.group(4))
    return int(low), int(high)


def _first_at_or_after(positions: list[int], cursor: int) -> int | None:
    k = bisect.bisect_left(positions, cursor)
    return positions[k] if k < len(positions) else None


def locate_sections(
    lines: list[BodyLine], expected: list[TocEntry]
) -> tuple[list[_Located], list[str]]:
    starts = _start_index(lines)
    located: list[_Located] = []
    missing: list[str] = []
    cursor = 0
    k = 0
    while k < len(expected):
        entry = expected[k]
        position = _first_at_or_after(starts.get(entry.section, []), cursor)
        following = (
            _first_at_or_after(starts.get(expected[k + 1].section, []), cursor)
            if k + 1 < len(expected)
            else None
        )
        if position is None or (following is not None and following < position):
            missing.append(entry.section)
            k += 1
            continue
        group = [entry]
        if bounds := _range_bounds(lines[position].text):
            # The range also covers lettered sections inside it: Sabah's
            # "Section 75 — 82" deletes 78A too.
            while k + len(group) < len(expected) and (
                bounds[0] <= _number(expected[k + len(group)].section) <= bounds[1]
            ):
                group.append(expected[k + len(group)])
        located.append(_Located(group, position))
        cursor = position + 1
        k += len(group)
    return located, missing


def _find_headers(lines: list[BodyLine], located: list[_Located]) -> None:
    """Find where each section's header (Part heading, title) begins.

    The header belongs to the section below it and must be cut from the end
    of the section above, or every section's last chunk ends with the next
    section's title.
    """
    floor = 0
    for loc in located:
        title = loc.entries[0].title
        title_start = loc.start
        if not title:
            # A deleted section can still print its old title in the body
            # (EA s.81G); the contents give none, so infer it by shape. One
            # line only: two lines would swallow the tail of the section above
            # (Sabah s.34 into s.35).
            if (k := _inferred_title_lines(lines, loc.start, floor, max_lines=1)) is not None:
                title_start = loc.start - k
                loc.title_inferred = True
        else:
            best, best_k = 0.0, 0
            # Up to ten lines: the IRA prints some titles one word per line.
            for k in range(1, 11):
                if loc.start - k < floor:
                    break
                candidate = " ".join(ln.text for ln in lines[loc.start - k : loc.start])
                score = _title_score(title, candidate)
                if score > best + 0.05:
                    best, best_k = score, k
            if best >= 0.6:
                title_start = loc.start - best_k
                loc.title_matched = True
            elif (k := _inferred_title_lines(lines, loc.start, floor)) is not None:
                # The printed title differs from the contents wording (Sabah
                # s.4: "Government inspections" vs "Powers of inspection and
                # inquiry."). Reported as inferred so a person can check it.
                title_start = loc.start - k
                loc.title_inferred = True
        if title_start < loc.start:
            loc.body_title = " ".join(
                " ".join(ln.text for ln in lines[title_start : loc.start]).split()
            ).rstrip(".")
        header_start = title_start
        for m in range(title_start - 1, max(floor, title_start - 8) - 1, -1):
            if _HEADING.match(lines[m].text):
                header_start = m
        loc.header_start = header_start
        floor = loc.start + 1


_TITLE_LIKE = re.compile(r"^[A-Z][^;:—]{2,118}$")
_SENTENCE_END = re.compile(r"[.;:—\]]\s*$")


def _inferred_title_lines(
    lines: list[BodyLine], start: int, floor: int, max_lines: int = 2
) -> int | None:
    """How many lines above a section start form its title, by shape alone.

    A title is one or two short lines starting with a capital, with no
    clause punctuation, sitting right after a line that ends a sentence.
    An all-capitals line is a Part heading's title, not a section title.
    """
    for k in range(1, max_lines + 1):
        # The line above may be the previous section's own start, as when
        # it is a one-line placeholder ("Section 101. [Deleted by AA1238]").
        if start - k - 1 < floor - 1:
            return None
        block = [ln.text.strip() for ln in lines[start - k : start]]
        before = lines[start - k - 1].text.strip()
        if not _TITLE_LIKE.match(block[0]) or _PARAGRAPH.match(block[0]) or block[0].isupper():
            continue
        if _LINE_START.fullmatch(before.rstrip()) or re.fullmatch(r"\s*\*{0,3}\d+[A-Za-z]*\.", before):
            # A bare "34." above means the block is that section's text.
            continue
        if k == 2 and _SENTENCE_END.search(block[0]):
            continue
        if _SENTENCE_END.search(before) and all(len(b) <= 120 for b in block):
            return k
    return None


def _end_of_sections(lines: list[BodyLine], last_start: int) -> int:
    for number in range(last_start + 1, len(lines)):
        text = lines[number].text
        if _SCHEDULE_HEADING.match(text) or _END_MATTER.match(text):
            # "LAWS OF MALAYSIA" heads the amendment list in the EA and IRA.
            if number > 0 and lines[number - 1].text.strip() == "LAWS OF MALAYSIA":
                return number - 1
            return number
    return len(lines)


# --------------------------------------------------------------------------
# Building chunks
# --------------------------------------------------------------------------


def _slug(term: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", term.lower()).strip("_")


def _strip_number(text: str, section: str, is_range: bool) -> str:
    pattern = _RANGE_START if is_range else re.compile(
        rf"^\s*\*{{0,3}}(?:Section\s+)?{re.escape(section)}\.", re.IGNORECASE
    )
    return re.sub(r"^\s*[—–-]?\s*", "", pattern.sub("", text, count=1))


class _Builder:
    def __init__(self, doc: dict, pages: list[Page], known: set[str]):
        self.doc = doc
        self.notes = {p.index: list(p.footnotes) for p in pages if p.footnotes}
        self.assigned: set[tuple[int, int]] = set()
        self.known = known
        self.chunks: list[dict] = []

    def chunk(
        self,
        entry: TocEntry,
        loc: _Located,
        lines: list[BodyLine],
        *,
        subsection: str | None,
        chunk_type: str,
        parse_rule: str,
        status: str,
        deleted_by: str | None = None,
        term: str | None = None,
        scope: str | None = None,
        annotations: list[str] = (),
    ) -> None:
        doc = self.doc
        content = join_lines([ln.text for ln in lines])
        sub_id = subsection.strip("()") if subsection else None
        chunk_id = f"{doc['chunk_prefix']}_s{entry.section}" + (f"_{sub_id}" if sub_id else "")
        citation = f"{doc['short_name']}, s. {entry.section}{subsection or ''}"
        if term:
            chunk_id += f"_def_{_slug(term)}"
            citation += f", definition of “{term}”"
            while any(c["chunk_id"] == chunk_id for c in self.chunks[-200:]):
                chunk_id += "_x"
        printed = [ln.printed_page for ln in lines if ln.printed_page is not None]
        raw = " ".join(ln.text for ln in lines)
        self.chunks.append(
            {
                "chunk_id": chunk_id,
                "doc_id": doc["id"],
                "statute": doc["short_name"],
                "act_number": doc["act_number"],
                "part": entry.part,
                "part_title": entry.part_title,
                "chapter": entry.chapter,
                "chapter_title": entry.chapter_title,
                "section": entry.section,
                "section_title": loc.body_title or entry.title,
                "subsection": subsection,
                "citation": citation,
                "chunk_type": chunk_type,
                "defined_term": term,
                "definition_scope": scope,
                "content": content,
                "status": status,
                "deleted_by": deleted_by,
                "cross_references_internal": internal_references(raw, self.known),
                "cross_references_external": external_references(raw, doc["short_name"]),
                "in_force_notes": self._notes_for(lines),
                "amendment_annotations": list(annotations),
                "jurisdiction": doc["jurisdiction_label"],
                "source_version": doc["source_version"],
                "as_at": str(doc["as_at"]),
                "source_page": printed[0] if printed else None,
                "source_page_end": printed[-1] if printed else None,
                "source_url": doc.get("source_url"),
                "parse_rule": parse_rule,
                "_page_indexes": sorted({ln.page_index for ln in lines}),
            }
        )

    def _notes_for(self, lines: list[BodyLine]) -> list[str]:
        """Attach a page's footnotes to the chunk carrying its "*" marker."""
        notes: list[str] = []
        for line in lines:
            if "*" not in line.text:
                continue
            for k, note in enumerate(self.notes.get(line.page_index, [])):
                if (line.page_index, k) not in self.assigned:
                    self.assigned.add((line.page_index, k))
                    notes.append(note)
                    break
        return notes

    def assign_leftover_notes(self) -> None:
        """Attach notes whose "*" marker was lost or sits in a heading.

        Prefer chunks of the section the note names ("Section 12A inserted
        is not yet in force"); otherwise every chunk on the note's page. A
        caveat attached too widely is a smaller failure than one lost.
        """
        for page, note in self.unassigned_notes():
            on_page = [c for c in self.chunks if page in c["_page_indexes"]]
            named = re.findall(r"\b[Ss]ection (\d+[A-Z]*)\b", note)
            targets = [c for c in on_page if c["section"] in named] or on_page
            if not targets:
                continue
            for chunk in targets:
                chunk["in_force_notes"].append(note)
            index = self.notes[page].index(note)
            self.assigned.add((page, index))

    def unassigned_notes(self) -> list[tuple[int, str]]:
        return [
            (page, note)
            for page, notes in self.notes.items()
            for k, note in enumerate(notes)
            if (page, k) not in self.assigned
        ]


def _section_status(entry: TocEntry) -> str:
    return "not_yet_in_force" if entry.not_yet_in_force else "in_force"


def _emit_section(builder: _Builder, loc: _Located, lines: list[BodyLine]) -> None:
    entry = loc.entries[0]
    is_range = len(loc.entries) > 1 or _range_bounds(lines[0].text) is not None
    first = BodyLine(lines[0].page_index, lines[0].printed_page, _strip_number(lines[0].text, entry.section, is_range))
    lines = [first] + lines[1:] if first.text.strip() else lines[1:]
    lines, annotations = lift_annotations(lines)

    placeholder = parse_placeholder(" ".join(ln.text for ln in lines)) if lines else None
    if placeholder or not lines:
        status, by = placeholder or (entry.status, entry.deleted_by)
        for each in loc.entries:
            builder.chunk(
                each, loc, lines or [first], subsection=None, chunk_type="provision",
                parse_rule="range_placeholder" if is_range else "placeholder",
                status=status, deleted_by=by or each.deleted_by, annotations=annotations,
            )
        return

    for subsection, sub_lines in split_subsections(lines):
        sub_lines = [ln for ln in sub_lines if ln.text.strip()]
        if not sub_lines:
            continue
        placeholder = parse_placeholder(" ".join(ln.text for ln in sub_lines))
        scope, definitions = split_definitions(sub_lines)
        rule = "subsection" if subsection else "section_undivided"
        if placeholder:
            builder.chunk(entry, loc, sub_lines, subsection=subsection, chunk_type="provision",
                          parse_rule="placeholder", status=placeholder[0], deleted_by=placeholder[1],
                          annotations=annotations)
        elif definitions:
            for term, def_lines in definitions:
                builder.chunk(entry, loc, def_lines, subsection=subsection, chunk_type="definition",
                              parse_rule="definition", status=_section_status(entry), term=term,
                              scope=scope, annotations=annotations)
        else:
            builder.chunk(entry, loc, sub_lines, subsection=subsection, chunk_type="provision",
                          parse_rule=rule, status=_section_status(entry), annotations=annotations)


def parse_document(doc: dict, raw_dir: str | Path) -> tuple[list[dict], dict]:
    """Parse one registry document's sections into chunks plus a coverage report."""
    pages = extract_pages(Path(raw_dir) / doc["file"])
    chunks, report, _ = parse_body(doc, pages, inventory_for_document(doc, raw_dir))
    return chunks, report


def parse_body(
    doc: dict, pages: list[Page], inventory: list[TocEntry]
) -> tuple[list[dict], dict, list[BodyLine]]:
    """Parse the sections; also return the lines after them (the schedules)."""
    expected = [e for e in inventory if e.kind == "section"]
    lines = body_lines(pages, doc["toc_pages"][1] + 1)

    located, missing = locate_sections(lines, expected)
    _find_headers(lines, located)
    end = _end_of_sections(lines, located[-1].start) if located else len(lines)

    builder = _Builder(doc, pages, {e.section for e in expected})
    for k, loc in enumerate(located):
        stop = located[k + 1].header_start if k + 1 < len(located) else end
        _emit_section(builder, loc, lines[loc.start : stop])

    builder.assign_leftover_notes()
    for chunk in builder.chunks:
        del chunk["_page_indexes"]

    report = {
        "doc_id": doc["id"],
        "expected": len(expected),
        "located": sum(len(loc.entries) for loc in located),
        "missing": missing,
        "titles_unmatched": [
            loc.entries[0].section
            for loc in located
            if loc.entries[0].title and not loc.title_matched and not loc.title_inferred
        ],
        "titles_inferred": {
            loc.entries[0].section: loc.body_title for loc in located if loc.title_inferred
        },
        "unassigned_notes": len(builder.unassigned_notes()),
        "chunks": len(builder.chunks),
        "schedule_start_line": end,
    }
    return builder.chunks, report, lines[end:]
