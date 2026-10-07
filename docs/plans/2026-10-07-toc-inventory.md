# Plan: `src/ingestion/toc.py` (expected-section inventory)

Status: done 2026-10-07. Decisions 1 to 3 approved as recommended.

## Goal

Read each document's ARRANGEMENT OF SECTIONS into a list of every section the
document says it contains. The validator (later step) diffs the parser's chunks
against this list: any section listed here with no chunk is a parser failure.

The inventory is built from the contents pages only, never from the body, so
it is an independent check on the parser rather than a copy of its output.

## Scope

| Document | Contents pages (0-based PDF index) | In scope |
|---|---|---|
| Employment Act 1955 | 2 to 10 | Yes |
| Industrial Relations Act 1967 | 2 to 7 | Yes |
| Labour Ordinance Sabah Cap. 67 | 0 to 12 | Yes |
| Labour Ordinance Sarawak Cap. 76 | 2 to 11 | Yes |
| Act A1754 | none | **No.** As-passed amending Act, has no contents pages. Its inventory ("Amendment of section N" headings) belongs to the amendment-linking step. |

Page ranges go in `config/config.yaml` per document as `toc_pages: [first, last]`,
the same way `first_schedule_page` is already declared. Auto-detecting where
the contents end is possible but fragile, and a wrong guess silently drops
sections. A corpus test pins each range.

## Output

```python
@dataclass(frozen=True)
class TocEntry:
    doc_id: str                 # registry id from config.yaml
    kind: str                   # "section" | "schedule"
    section: str                # "60FA", "121AU", "FIRST SCHEDULE"; upper-cased
    title: str | None           # "Paternity leave"; None for a bare placeholder
    part: str | None            # "Part XII"
    chapter: str | None         # "Chapter IIA" (Sabah, Sarawak only)
    status: str                 # "listed" | "deleted" | "omitted"
    deleted_by: str | None      # "AA1238", "Act A1237", or None ("(Deleted)" names no instrument)
    not_yet_in_force: bool      # Sabah 121A to 121AU
```

Written to `data/processed/toc_inventory.jsonl`, one entry per line.

## Formats the parser must handle (all seen in the real output)

1. **Number and title on one line, or split across two.** EA: `1.` then
   `Short title and application`; also `3.   Appointment of officers`.
   Sabah always inline: `7A. Director's power to inquire into complaints`.
2. **Titles that wrap.** `Contracts of service not to restrict rights of
   employees to join, participate in` / `or organize trade unions`.
   Continuation lines are appended until the next number, PART, CHAPTER or
   SCHEDULE line.
3. **Ranges.** EA `34-36.    (Deleted)` and `45-56.`; Sabah `19 — 33. [Deleted
   by AA1238]`. Expanded to one entry per section. Only plain-number ranges
   occur, so no letter-suffix range expansion is needed.
4. **Placeholder status, four spellings.** `(Deleted)`, `(Omitted)`,
   `[Deleted by AA1238]`, `[Deleted by Act A1237.]`. The instrument is kept in
   `deleted_by`.
5. **Headings.** EA and IRA: `PART XIIA` then a title line, which may wrap.
   Sabah: `PART I — LABOUR DEPARTMENT` inline, plus `CHAPTER IIA` then a
   mixed-case title. Sarawak: `PART   I` (extra spaces) plus CHAPTER. Deleted
   parts and chapters (`CHAPTER VIII` / `[Deleted by AA1238]`) are tracked as
   headings, not entries.
6. **Noise to drop.** The `Section` column header; running headers the
   extractor missed on contents pages (`4  Laws of Malaysia` / `ACT 265`,
   `Laws of Malaysia   ACT 177`, `CAP. 76 (1948 ED.)`); a stray `\\` on EA p.4.
7. **Not yet in force.** Sabah's `(NOT YET IN FORCE) (Section 121A — 121AU)`
   marks every entry in that range. The parsed range must match the
   `commencement_exceptions` already in config, and a test checks that.
8. **Schedules.** `FIRST SCHEDULE`, `SECOND SCHEDULE` lines become
   `kind: "schedule"` entries so the validator also checks schedule coverage.

## Sanity checks built into the parser

- No duplicate section ids within a document.
- The numeric part of section ids never decreases. Letter suffixes are **not**
  order-checked: the EA puts `60FA` between `60F` and `60G`, while Sabah puts
  `121AA` after `121Z`, so no single ordering fits both.
- A line that looks like neither an entry, a heading, a continuation nor known
  noise raises an error naming the page and line, rather than being skipped.

## Tests (TDD, written before the code)

Unit tests in `tests/unit/test_toc.py`, fixture strings copied from real
extractor output (same convention as `test_extract.py`), one test per format
above.

Corpus tests (marker `corpus`):
- EA: first `1`, last `103`, contains `60FA`, `34`/`35`/`36` deleted,
  `17` omitted, two schedules.
- IRA: contains `12A`, `12B`, `51A` to `51F`, `33A` deleted.
- Sabah: `121A` to `121AU` all present and `not_yet_in_force`, `7C`
  `deleted_by == "AA1753"`.
- Sarawak: `5` `deleted_by == "Act A1237"`, `130A` present.
- Each document: total section count equals a hand count recorded once in the
  test, so any later regression shows up as a number change.

## Side finding (not fixed in this task)

`extract.py` misses some running headers on contents pages: the EA verso
pages come back with `printed_page = None` and the header left in the text,
and the IRA and Sarawak contents pages leak `Laws of Malaysia ACT 177` and
`CAP. 76 (1948 ED.)`. `toc.py` drops these lines itself. Whether the same
leak happens on body pages needs checking before the section parser starts.

## Decisions needing approval

1. Contents page ranges declared in config, not auto-detected. (Recommended.)
2. `(Omitted)` sections count as expected, the same as `(Deleted)`, so they
   must also get a placeholder chunk. (Recommended, matches the schema rule
   that placeholders are never dropped.)
3. Act A1754 is excluded from this task.
