"""Act A1754: chunk the amending Act and link it to Sarawak Cap. 76.

Cap. 76 and A1754 stay two separate documents (CLAUDE.md, config.yaml):
the principal text is never re-consolidated, so every provision a user sees
can be checked against a published instrument. They are linked instead.

Each A1754 section opens with a title naming what it changes ("Amendment of
section 84", "Deletion of sections 8c, 8d and 8e", "New Part IVa"), which
gives the link target. Long sections are split, first at each inserted Cap.
76 section ("122a." in the new Part IVa), then at instruction paragraphs
("(a) by substituting ...", "(iii) in the definition of ..."). Each part is
linked to the narrowest Cap. 76 chunk it names: a definition, a subsection,
or else the whole section.

Effects on Cap. 76 chunks, all from 1 May 2025 (config commencement):
    amended or substituted   status "superseded", amended_by -> A1754 chunks
    deleted                  status "deleted", deleted_by "Act A1754"

The A1754 text is the as-passed Act, so its own s.1(2) still reads "a date
to be appointed". Commencement comes from config: everything is in force
except s.52 (new Part IVa), which is not.

Section 2 ("worker" becomes "employee" throughout) touches every chunk and
is applied at prompt time from config jurisdiction_notes, not linked here.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.ingestion.extract import extract_pages
from src.ingestion.sections import BodyLine, body_lines, external_references, join_lines

_SECTION_START = re.compile(r"^\s*(\d+)\.(?=\s|$)")
_INSERTED_START = re.compile(r"^\s*[‘'“\"]?\s*(\d+[a-z]{1,3})\.(?=\s|$)")
_INSTRUCTION = {
    1: re.compile(r"^\s*\(([a-z]{1,2})\)\s+(?:by|in)\b"),
    2: re.compile(r"^\s*\(((?:x{0,3})(?:ix|iv|v?i{0,3}))\)\s+(?:by|in)\b"),
}
_MAX_WORDS = 450

_TITLE_RULES = [
    (re.compile(r"^Amendment of sections? (.+)$"), "amend"),
    (re.compile(r"^Substitution of sections? (.+)$"), "substitute"),
    (re.compile(r"^Deletion of sections? (.+)$"), "delete"),
    (re.compile(r"^New sections? (.+)$"), "insert"),
    (re.compile(r"^Deletion of (Chapter \w+)$"), "delete_chapter"),
    (re.compile(r"^Amendment of (Chapter \w+)$"), "amend_heading"),
    (re.compile(r"^New (Chapter \w+)$"), "insert_chapter"),
    (re.compile(r"^New (Part \w+)$"), "insert_part"),
    (re.compile(r"^Substitution of (Schedule)$"), "substitute_schedule"),
    (re.compile(r"^New .*Schedules?$"), "insert_schedule"),
    (re.compile(r"^General amendments$"), "general"),
]


def _upper_suffix(label: str) -> str:
    """"Chapter XIa" -> "Chapter XIA": Cap. 76 upper-cases ids, A1754 does not."""
    kind, _, ident = label.partition(" ")
    return f"{kind} {ident.upper()}"


def read_title(title: str) -> tuple[str, list[str]]:
    """Read an A1754 section title into (action, targets)."""
    title = " ".join(title.split()).rstrip(".")
    for pattern, action in _TITLE_RULES:
        if match := pattern.match(title):
            if action == "general":
                return action, []
            if action == "insert_schedule":
                return action, []
            if action == "substitute_schedule":
                return action, ["SCHEDULE"]
            raw = match.group(1)
            if action in ("delete_chapter", "amend_heading", "insert_chapter", "insert_part"):
                return action, [_upper_suffix(raw)]
            return action, [s.upper() for s in re.findall(r"\d+[a-z]*", raw)]
    return "other", []


def narrow_target(first_line: str) -> tuple[str | None, str | None, str | None]:
    """(section, subsection, defined term) named at the start of a part."""
    text = " ".join(first_line.split())
    if match := re.match(r"^(?:Subsection|Paragraph|Subparagraph) (\d+[a-z]*)\((\d+[A-Za-z]?)\)", text):
        return match.group(1).upper(), f"({match.group(2)})", None
    # "(c) in subsection (4)", "(b) in paragraph (3)(c)": paragraph (3)(c)
    # is inside subsection (3).
    if match := re.match(
        r"^\(\w+\) (?:by substituting for|by deleting|in) (?:subsection|paragraph) \((\d+[A-Z]?)\)", text
    ):
        return None, f"({match.group(1)})", None
    if not inserts_definition(text):
        if match := re.search(r"(?:in|for|deleting) the definition of “([^”]+)”", text):
            return None, None, match.group(1)
    return None, None, None


def inserts_definition(first_line: str) -> bool:
    """A new definition placed after an existing one changes nothing that exists."""
    # Also "after the deleted definition of “ship”" (s.3(a)(xvii)).
    return bool(re.search(r"by inserting after the (?:deleted )?definition of", " ".join(first_line.split())))


def deletes_whole(first_line: str) -> bool:
    """Whether a part deletes a whole definition or subsection, not just words."""
    text = " ".join(first_line.split())
    return bool(re.match(r"^\(\w+\) by deleting (?:the definition of|subsection|paragraph \()", text))


def _title_run_start(lines: list[BodyLine], start: int, floor: int) -> int:
    """Where the heading above an inserted section begins.

    A1754 prints inserted-section titles in a narrow margin ("Application
    for" / "flexible working" / "arrangement."), so they arrive as short
    lines just above the number; Part and Chapter headings ("SPECIAL
    PROVISIONS RELATING TO EMPLOYEES’") arrive as upper-case lines above that.
    """
    k = start
    while k - 1 > floor and start - k < 8:
        text = lines[k - 1].text.strip()
        short_title = len(text) <= 30 and not re.search(r"[;:—]$", text)
        if not (short_title or text.isupper()):
            break
        k -= 1
    while k < start and lines[k].text.strip()[:1].islower():
        k += 1
    return k


_LETTERS = [chr(c) for c in range(ord("a"), ord("z") + 1)]
_ROMAN = "i ii iii iv v vi vii viii ix x xi xii xiii xiv xv xvi xvii xviii xix xx xxi xxii xxiii xxiv xxv".split()
_MARKER = re.compile(r"^\s*\(([a-z]{1,5})\)\s+(?:by|in)\b")
_MIN_WORDS = 15

Narrow = tuple[str | None, str | None, str | None]
Piece = tuple[str | None, list[BodyLine], Narrow, str]


def _markers(lines: list[BodyLine], sequence: list[str]) -> list[tuple[int, str]]:
    """Instruction paragraphs in sequence only: (a), (b), (c) ... or (i), (ii) ...

    Checking the sequence keeps "(i)" (a roman sub-paragraph) from being read
    as the ninth lettered paragraph.
    """
    starts, expected = [], 0
    for k, line in enumerate(lines):
        match = _MARKER.match(line.text)
        if match and expected < len(sequence) and match.group(1) == sequence[expected]:
            starts.append((k, match.group(1)))
            expected += 1
    return starts


def _merge_small(pieces: list[Piece]) -> list[Piece]:
    """Fold lead-ins such as "(a) in subsection (1)—" into the part they open.

    Only a lead-in (short, ending in a dash or colon) is folded. A short but
    complete instruction, "(ix) by deleting the definition of “family”;",
    stays its own chunk: it is the only record of that deletion.
    """
    merged: list[Piece] = []
    carry: list[BodyLine] = []
    for n, (label, lines, narrow, head) in enumerate(pieces):
        lines = carry + lines
        carry = []
        text = " ".join(ln.text for ln in lines).strip()
        is_lead_in = len(text.split()) < _MIN_WORDS and text.endswith(("—", ":", "-"))
        if n + 1 < len(pieces) and is_lead_in:
            carry = lines
            continue
        merged.append((label, lines, narrow, head))
    return merged


def _head(lines: list[BodyLine], at: int = 0) -> str:
    """The opening of a piece, read to find its target.

    Two lines, since a term can wrap ("definition of" / "“part-time
    employee”"), unless the second line opens the next instruction.
    """
    head = lines[at].text if at < len(lines) else ""
    if at + 1 < len(lines) and not _MARKER.match(lines[at + 1].text):
        head += " " + lines[at + 1].text
    return head


def _split(lines: list[BodyLine], level: int = 0, inherited: Narrow = (None, None, None)) -> list[Piece]:
    """Split a long section at inserted sections, then instruction paragraphs.

    Each piece carries the narrowest target it or an enclosing paragraph
    names, so "(d)(i) by inserting after the word ..." still points at
    subsection (6) from "(d) in subsection (6)—".
    """
    head = _head(lines)
    if sum(len(ln.text.split()) for ln in lines) <= _MAX_WORDS or level > 2:
        return [(None, lines, inherited, head)]

    if level == 0:
        starts = [k for k, ln in enumerate(lines) if k > 0 and _INSERTED_START.match(ln.text)]
        if not starts:
            return _split(lines, 1, inherited)
        bounds, floor = [], 0
        for k in starts:
            bounds.append(_title_run_start(lines, k, floor))
            floor = k
        pieces: list[Piece] = [(None, lines[: bounds[0]], inherited, head)] if bounds[0] > 0 else []
        for n, begin in enumerate(bounds):
            end = bounds[n + 1] if n + 1 < len(bounds) else len(lines)
            label = _INSERTED_START.match(lines[starts[n]].text).group(1).upper()
            pieces.append((f"new {label}", lines[begin:end], (None, None, None), _head(lines, starts[n])))
        return _merge_small([p for p in pieces if p[1]])

    starts = _markers(lines, _LETTERS if level == 1 else _ROMAN)
    if not starts:
        return _split(lines, level + 1, inherited) if level < 2 else [(None, lines, inherited, head)]
    pieces = [(None, lines[: starts[0][0]], inherited, head)] if starts[0][0] > 0 else []
    for n, (begin, mark) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
        own = narrow_target(_head(lines, begin))
        narrow = tuple(o or i for o, i in zip(own, inherited))
        children = (
            _split(lines[begin:end], level + 1, narrow)
            if level < 2
            else [(None, lines[begin:end], narrow, _head(lines, begin))]
        )
        for sub_label, sub_lines, sub_narrow, sub_head in children:
            pieces.append((f"({mark})" + (sub_label or ""), sub_lines, sub_narrow, sub_head))
    return _merge_small(pieces)


def _locate(lines: list[BodyLine]) -> tuple[list[tuple[int, int, str]], list[int]]:
    """Find sections 1, 2, 3 ... in order; (number, line, title) and missing."""
    found, missing = [], []
    cursor, expected = 0, 1
    while cursor < len(lines):
        hit = next(
            (k for k in range(cursor, len(lines)) if (m := _SECTION_START.match(lines[k].text)) and int(m.group(1)) == expected),
            None,
        )
        if hit is None:
            break
        title = lines[hit - 1].text.strip() if hit > 0 else ""
        found.append((expected, hit, title))
        cursor, expected = hit + 1, expected + 1
    return found, missing


def parse_amending_act(doc: dict, config: dict) -> tuple[list[dict], dict]:
    """Chunk A1754 into amendment chunks, with link targets recorded."""
    raw_dir = Path(config["corpus"]["raw_dir"])
    pages = extract_pages(raw_dir / doc["file"])
    lines = body_lines(pages, 0)
    located, missing = _locate(lines)
    not_in_force = {e["source_section"] for e in doc.get("commencement_exceptions", [])}

    chunks: list[dict] = []
    for n, (number, start, title) in enumerate(located):
        stop = located[n + 1][1] - 1 if n + 1 < len(located) else len(lines)
        section_lines = lines[start:stop]
        first = BodyLine(section_lines[0].page_index, section_lines[0].printed_page,
                         _SECTION_START.sub("", section_lines[0].text, count=1))
        section_lines = [first] + section_lines[1:]
        action, targets = read_title(title)
        parts = _split(section_lines, inherited=narrow_target(_head(section_lines)))
        for label, part, narrow, head in parts:
            part = [ln for ln in part if ln.text.strip()]
            if not part:
                continue
            chunk_id = f"{doc['chunk_prefix']}_s{number}"
            citation = f"{doc['short_name']}, s. {number}"
            inserts = targets if action == "insert" and len(parts) == 1 else []
            if label and label.startswith("new "):
                inserted = label[4:]
                chunk_id += f"_{inserted}"
                citation += f" (new section {inserted.lower()})"
                inserts = [inserted]
            elif label:
                chunk_id += "_" + "_".join(re.findall(r"\(([^)]+)\)", label))
                citation += label
            printed = [ln.printed_page for ln in part if ln.printed_page is not None]
            raw = " ".join(ln.text for ln in part)
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "doc_id": doc["id"],
                    "statute": doc["short_name"],
                    "act_number": doc["act_number"],
                    "part": None,
                    "part_title": None,
                    "chapter": None,
                    "chapter_title": None,
                    "section": str(number),
                    "section_title": " ".join(title.split()).rstrip("."),
                    "subsection": label,
                    "citation": citation,
                    "chunk_type": "amendment",
                    "defined_term": None,
                    "definition_scope": None,
                    "content": join_lines([ln.text for ln in part]),
                    "status": "not_yet_in_force" if str(number) in not_in_force else "in_force",
                    "deleted_by": None,
                    "cross_references_internal": [],
                    "cross_references_external": external_references(raw, doc["short_name"]),
                    "in_force_notes": [],
                    "amendment_annotations": [],
                    "jurisdiction": doc["jurisdiction_label"],
                    "source_version": doc["source_version"],
                    "as_at": str(doc.get("commencement", doc.get("as_at"))),
                    "source_page": printed[0] if printed else None,
                    "source_page_end": printed[-1] if printed else None,
                    "source_url": doc.get("source_url"),
                    "parse_rule": "amendment_part" if label else "amendment_section",
                    "amendment_action": action,
                    "target_sections": targets,
                    "inserts": inserts,
                    "amends": [],
                    "amendment_status": "not_yet_in_force" if str(number) in not_in_force else "in_force",
                    "commencement": None if str(number) in not_in_force else str(doc.get("commencement")),
                    "_narrow": narrow,
                    "_inserts_definition": inserts_definition(head),
                    "_deletes_whole": deletes_whole(head),
                }
            )
    report = {"doc_id": doc["id"], "sections": len(located), "missing": missing, "chunks": len(chunks)}
    return chunks, report


def link(principal: list[dict], amending: list[dict]) -> dict:
    """Write amends / amended_by links and statuses onto both chunk lists."""
    for chunk in principal:
        chunk.setdefault("amended_by", [])
    by_section: dict[str, list[dict]] = {}
    for chunk in principal:
        by_section.setdefault(chunk["section"], []).append(chunk)

    unresolved: list[str] = []
    for source in amending:
        action, targets = source["amendment_action"], source["target_sections"]
        section_narrow, subsection, term = source.pop("_narrow")
        if source.pop("_inserts_definition"):
            continue
        deletes = action == "delete" or (source.pop("_deletes_whole") and (term or subsection))
        if action in ("amend", "substitute", "delete"):
            pool = [c for s in ([section_narrow] if section_narrow else targets) for c in by_section.get(s, [])]
        elif action == "delete_chapter":
            pool = [c for c in principal if c["chapter"] == targets[0]]
        elif action == "substitute_schedule":
            pool = [c for c in principal if c["section"] == "SCHEDULE"]
        else:
            continue
        if not pool:
            unresolved.append(f"{source['chunk_id']} -> {targets}")
            continue
        narrowed = pool
        if term:
            narrowed = [c for c in pool if c.get("defined_term") == term] or pool
        elif subsection:
            narrowed = [c for c in pool if c["subsection"] == subsection] or pool
        for target in narrowed:
            source["amends"].append(target["chunk_id"])
            target["amended_by"].append(source["chunk_id"])
            if deletes or action == "delete_chapter":
                target["status"], target["deleted_by"] = "deleted", "Act A1754"
            elif target["status"] != "deleted":
                target["status"] = "superseded"

    for chunk in amending:
        for key in ("_narrow", "_inserts_definition", "_deletes_whole"):
            chunk.pop(key, None)
    return {
        "unresolved": unresolved,
        "superseded": sum(c["status"] == "superseded" for c in principal),
        "deleted_by_a1754": sum(c.get("deleted_by") == "Act A1754" for c in principal),
    }
