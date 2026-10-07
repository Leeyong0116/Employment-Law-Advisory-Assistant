"""Page-preserving text extraction for the statutory corpus.

This is the bottom of the ingestion stack. It turns a source PDF into clean
per-page text while preserving the one thing every downstream citation needs:
the page number *printed on the page*, which is not the PDF page index and
whose offset differs per document and in direction (Sabah index 40 carries
printed 41; Sarawak Cap. 76 index 41 carries printed 40).

Four artifacts are handled here so the section parser never sees them:

* Running headers and footers, which in the EA land mid-sentence inside the
  proviso to s.60E(1). They are located first (that is where the printed page
  number lives) and only then removed.
* Editorial footnotes, separated from the body by a rule of Symbol-font
  glyphs. These carry the IRA not-yet-in-force annotations and are AGC
  commentary rather than statute, so they must never reach a chunk content
  field.
* Letter-spaced justified lines, where inter-letter and inter-word gaps both
  collapse to a single space in the text layer. Word boundaries are recovered
  from x-coordinates instead.
* Watermarks, in Sarawak Cap. 76.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pymupdf

EM_DASH = "—"

# The IRA reprint draws its footnote rule with a Symbol-font private-use
# glyph, and loses the em-dash in "*NOTE--" to a replacement character.
_GLYPH_MAP = {"": EM_DASH, "�": EM_DASH, "–": EM_DASH}

_DIGIT_RUN = re.compile(r"\d+")
_LEADING_NUMBER = re.compile(r"^\s*(\d{1,3})\b")
_TRAILING_NUMBER = re.compile(r"\b(\d{1,3})\s*$")
# "ACT 265", "Cap. 67", "No. 38" are identifiers, never page numbers.
_NOT_A_PAGE_NUMBER = re.compile(r"\b(?:act|cap\.?|chapter|no\.?)\s*\d+\s*$", re.IGNORECASE)
_LETTER_SPACED = re.compile(r"(?:\b\w ){4,}\w\b")
# The EA marks footnotes with a bare "*NOTE"; a second note on the same page
# uses "**NOTE". Statutory text never begins this way.
_NOTE_MARKER = re.compile(r"^\*+\s*NOTE\b")

# How many lines at each edge of a page can be furniture, and how often a line
# must recur in the same slot before it counts as furniture. The EA alternates
# recto and verso headers, so each appears on only about half the pages and the
# threshold has to sit below that.
_EDGE_LINES = 2
_FURNITURE_RATIO = 0.3

# Sarawak Cap. 76 runs a three-line header ("Sarawak Lawnet" / "LABOUR" /
# "39"), putting the page number one line outside the furniture window. The
# window is not widened for everything -- position 2 elsewhere holds subsection
# markers like "(2)" and "(c)", and stripping those would destroy the
# numbering. Only a line that is nothing but digits is claimed this far in,
# which at a page edge is always a page number and never statutory text.
_PAGE_NUMBER_WINDOW = 3

# The same three-line header puts a running title on the third line too:
# "CAP. 76 (1948 ED.)" in Cap. 76 and "Act A1754" in the amending Act, both on
# verso pages. Left in, it lands mid-provision wherever a section crosses a
# page. The third line is furniture only when its signature recurs in that
# slot across the document AND it is not numbering: "(2)" or "12." can recur
# there by chance and must never be stripped.
_DEEP_EDGE_LINES = 3
_STRUCTURAL = re.compile(r"^\s*(?:\(\w{1,5}\)|\d+[A-Za-z]*\.)")


@dataclass(frozen=True)
class Page:
    """One page of a source document, cleaned but not yet parsed."""

    index: int
    """0-based PDF page index."""

    printed_page: int | None
    """The page number printed on the page, for a chunk source_page field.
    None when the page carries none -- a citation must never invent one."""

    text: str
    """Body text, with furniture, footnotes and watermarks removed."""

    furniture: tuple[str, ...] = ()
    """The header and footer lines that were removed."""

    footnotes: tuple[str, ...] = ()
    """Editorial footnotes, verbatim. These feed a chunk in_force_notes."""


def normalise_glyphs(text: str) -> str:
    """Map font-specific and lost characters onto real Unicode."""
    for bad, good in _GLYPH_MAP.items():
        text = text.replace(bad, good)
    return text


def digit_signature(line: str) -> str:
    """Collapse a line to a form that ignores page numbers.

    Lets "42  Laws of Malaysia  ACT 265" and "64  Laws of Malaysia  ACT 265"
    be recognised as the same running header.
    """
    return _DIGIT_RUN.sub("#", " ".join(line.split())).strip()


def _edge_slots(lines: list[str], depth: int = _EDGE_LINES) -> list[tuple[str, str]]:
    """Yield (slot, signature) pairs for the lines at each edge of a page.

    The slot matters as much as the frequency. Sabah has 143 lines reading
    "Section N. [Deleted by AAnnnn]", which share a digit signature and would
    look like furniture on frequency alone; they are not pinned to a page edge.
    """
    slots: list[tuple[str, str]] = []
    for offset in range(min(depth, len(lines))):
        slots.append((f"top{offset}", digit_signature(lines[offset])))
    for offset in range(min(depth, len(lines))):
        slots.append((f"bot{offset}", digit_signature(lines[-1 - offset])))
    return slots


def find_furniture_signatures(
    pages_lines: list[list[str]], depth: int = _EDGE_LINES
) -> set[str]:
    """Return the digit signatures of recurring running headers and footers."""
    counts: Counter[tuple[str, str]] = Counter()
    for lines in pages_lines:
        counts.update(set(_edge_slots([ln for ln in lines if ln.strip()], depth)))
    threshold = max(2, int(_FURNITURE_RATIO * len(pages_lines)))
    return {signature for (_slot, signature), n in counts.items() if n >= threshold}


def printed_page_number(furniture_lines: list[str]) -> int | None:
    """Read the printed page number off a page, or return None.

    A bare number on its own line wins; then a number at the start of a
    header; then one at the end. Trailing statute identifiers such as
    "ACT 265" are never treated as page numbers.
    """
    for line in furniture_lines:
        stripped = line.strip()
        if stripped.isdigit():
            return int(stripped)
    for line in furniture_lines:
        match = _LEADING_NUMBER.match(line)
        if match:
            return int(match.group(1))
    for line in furniture_lines:
        if _NOT_A_PAGE_NUMBER.search(line.strip()):
            continue
        match = _TRAILING_NUMBER.search(line)
        if match:
            return int(match.group(1))
    return None


def split_footnotes(lines: list[str]) -> tuple[list[str], list[str]]:
    """Split a page into body text and editorial footnotes.

    The corpus marks footnotes two different ways. The IRA draws a rule of
    Symbol-font dashes and puts its notes below it. The EA draws no rule and
    simply starts a line with "*NOTE" (or "**NOTE" for a second note on the
    same page). Either way the notes run to the foot of the page and wrap
    across lines, so continuations are folded back into one note each.
    """
    body_end = notes_start = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if len(stripped) >= 5 and set(stripped) == {EM_DASH}:
            body_end, notes_start = index, index + 1
        elif notes_start is None and _NOTE_MARKER.match(stripped):
            body_end = notes_start = index

    if notes_start is None:
        return list(lines), []

    notes: list[str] = []
    for line in (ln.strip() for ln in lines[notes_start:] if ln.strip()):
        if _NOTE_MARKER.match(line) or not notes:
            notes.append(line)
        else:
            notes[-1] = f"{notes[-1]} {line}"
    return list(lines[:body_end]), notes


def rejoin_letter_spaced(tokens: list[str], gaps: list[float]) -> str:
    """Rebuild words from single characters using the gaps between them.

    Justified lines in Act A1754 render as "h e h a s b e e n"; the gaps are
    bimodal (1.93pt within a word, 12.43pt between words), so the word breaks
    are recoverable even though both collapse to one space in the text layer.
    """
    if not tokens:
        return ""
    if not gaps or max(gaps) <= min(gaps) * 2:
        return "".join(tokens)
    threshold = (min(gaps) + max(gaps)) / 2
    out = [tokens[0]]
    for token, gap in zip(tokens[1:], gaps):
        out.append(" " + token if gap > threshold else token)
    return "".join(out)


def _repaired_lines(page: pymupdf.Page) -> dict[str, str]:
    """Map the collapsed form of each letter-spaced line to its repaired text."""
    grouped: dict[tuple[int, int], list[tuple]] = {}
    for word in page.get_text("words"):
        grouped.setdefault((word[5], word[6]), []).append(word)

    repaired: dict[str, str] = {}
    for words in grouped.values():
        if sum(1 for w in words if len(w[4]) == 1) < 5:
            continue
        words = sorted(words, key=lambda w: w[0])
        tokens = [w[4] for w in words]
        gaps = [round(b[0] - a[2], 2) for a, b in zip(words, words[1:])]
        repaired["".join(tokens)] = rejoin_letter_spaced(tokens, gaps)
    return repaired


def _edge_positions(lines: list[str], window: int = _EDGE_LINES):
    """Yield the positions on a page that are eligible to be furniture."""
    seen: set[int] = set()
    for offset in range(min(window, len(lines))):
        for position in (offset, len(lines) - 1 - offset):
            if 0 <= position < len(lines) and position not in seen:
                seen.add(position)
                yield position


def bare_page_number_positions(lines: list[str]) -> set[int]:
    """Positions of edge lines that consist of nothing but a page number."""
    return {
        position
        for position in _edge_positions(lines, _PAGE_NUMBER_WINDOW)
        if lines[position].strip().isdigit()
    }


def furniture_positions(
    lines: list[str], signatures: set[str], deep_signatures: set[str]
) -> set[int]:
    """Positions on one page that hold running headers, footers or page numbers."""
    positions = {
        position
        for position in _edge_positions(lines)
        if digit_signature(lines[position]) in signatures
    }
    for position in set(_edge_positions(lines, _DEEP_EDGE_LINES)) - set(_edge_positions(lines)):
        line = lines[position]
        if digit_signature(line) in deep_signatures and not _STRUCTURAL.match(line):
            positions.add(position)
    return positions | bare_page_number_positions(lines)


# A fraction bar is a short drawn line, not a character, so the text layer
# loses it: EA s.60I(1A) "monthly rate of pay / 26" extracts as
# "monthly rate of pay" / "." / "26", and the division is gone. Text within
# this distance above and below such a line is its numerator and denominator.
_FRACTION_REACH = 16.0


def _normal(text: str) -> str:
    return " ".join(text.split())


def find_fractions(page: pymupdf.Page) -> list[tuple[str, str]]:
    """(numerator, denominator) for each fraction bar drawn on the page.

    A short rule above a "*NOTE" is a footnote separator, not a fraction.
    """
    words = page.get_text("words")
    fractions = []
    for drawing in page.get_drawings():
        bar = drawing["rect"]
        if bar.height > 2 or not 15 < bar.width < 320:
            continue

        def side(top: float, bottom: float) -> str:
            hits = [w for w in words if top <= (w[3] if bottom <= bar.y0 + 2 else w[1]) <= bottom
                    and w[2] > bar.x0 and w[0] < bar.x1]
            return _normal(" ".join(w[4] for w in sorted(hits, key=lambda w: (round(w[1]), w[0]))))

        numerator = side(bar.y0 - _FRACTION_REACH, bar.y0 + 1.5)
        denominator = side(bar.y1 - 1.5, bar.y1 + _FRACTION_REACH)
        if numerator and denominator and not denominator.lstrip("*").startswith("NOTE"):
            fractions.append((numerator, denominator))
    return fractions


def _find_run(lines: list[str], text: str, start: int, stop: int) -> tuple[int, int] | None:
    """Where consecutive lines, joined, read exactly `text`: (index, count)."""
    wanted = _normal(text)
    for k in range(start, min(stop, len(lines))):
        for count in range(1, 5):
            if _normal(" ".join(lines[k : k + count])) == wanted:
                return k, count
    return None


_STRAY = {".", ";"}
# How far below the numerator the denominator may come out of the text
# layer: EA s.18A prints "X" and a second factor beside the fraction, and
# those lines arrive in between.
_DENOMINATOR_WINDOW = 8


def rewrite_fractions(lines: list[str], fractions: list[tuple[str, str]]) -> list[str]:
    """Rejoin each fraction as "numerator / denominator".

    Sides of more than four words are bracketed, so the division stays
    unambiguous next to other terms. Lines that came out between the two
    sides (the "X" and second factor of EA s.18A) follow the fraction, with
    "X" first. A stray full stop or semicolon from beside the bar ends it.
    """
    out = list(lines)
    for numerator, denominator in fractions:
        top = _find_run(out, numerator, 0, len(out))
        if top is None:
            continue
        start = top[0] + top[1]
        bottom = _find_run(out, denominator, start, start + _DENOMINATOR_WINDOW)
        if bottom is None:
            continue
        between = [ln.strip() for ln in out[start : bottom[0]]]
        end = bottom[0] + bottom[1]
        stray = [ln for ln in between if ln in _STRAY]
        if end < len(out) and out[end].strip() in _STRAY:
            stray.append(out[end].strip())
            end += 1
        between = [ln for ln in between if ln not in _STRAY]
        if "X" in between:
            between = ["X"] + [ln for ln in between if ln != "X"]
        wrap = max(len(numerator.split()), len(denominator.split())) > 4
        formula = f"({numerator}) / ({denominator})" if wrap else f"{numerator} / {denominator}"
        formula = " ".join([formula] + between) + (stray[0] if stray else "")
        out[top[0] : end] = [formula]
    return out


def _repair(line: str, repairs: dict[str, str]) -> str:
    if not _LETTER_SPACED.search(line):
        return line
    return repairs.get("".join(line.split()), line)


def extract_pages(
    path: str | Path, *, watermark_patterns: tuple[str, ...] = ()
) -> list[Page]:
    """Extract every page of a source PDF as cleaned, page-numbered text."""
    path = Path(path)
    raw_pages: list[list[str]] = []
    repairs: list[dict[str, str]] = []
    with pymupdf.open(path) as document:
        for page in document:
            lines = [normalise_glyphs(ln).rstrip() for ln in page.get_text().splitlines()]
            lines = [
                ln
                for ln in lines
                if ln.strip() and not any(p in ln for p in watermark_patterns)
            ]
            lines = rewrite_fractions(lines, find_fractions(page))
            raw_pages.append(lines)
            repairs.append(_repaired_lines(page))

    signatures = find_furniture_signatures(raw_pages)
    deep_signatures = find_furniture_signatures(raw_pages, _DEEP_EDGE_LINES)

    pages: list[Page] = []
    for index, lines in enumerate(raw_pages):
        positions = furniture_positions(lines, signatures, deep_signatures)
        furniture = [lines[p] for p in sorted(positions)]
        body = [
            _repair(line, repairs[index])
            for position, line in enumerate(lines)
            if position not in positions
        ]
        body, footnotes = split_footnotes(body)
        pages.append(
            Page(
                index=index,
                printed_page=printed_page_number(furniture),
                text="\n".join(body).strip(),
                furniture=tuple(furniture),
                footnotes=tuple(footnotes),
            )
        )
    return pages
