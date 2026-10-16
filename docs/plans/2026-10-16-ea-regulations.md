# Plan: index two Employment Act regulations (2026-10-16)

## Goal

Add the two pieces of subsidiary legislation that hold numbers the corpus
lacks, found during the gold-set review (devlog 2026-10-10, data issues):

| Instrument | Holds | Source |
|---|---|---|
| Employment (Limitation of Overtime Work) Regulations 1980 | 104 hours a month overtime limit (reg. 2), made for EA s.60A(4)(a) | JTKSM PDF, 2 pages |
| Employment (Termination and Lay-Off Benefits) Regulations 1980 | 10 / 15 / 20 days' wages per year (reg. 6), 7-day payment (reg. 11) | JTKSM PDF, 8 pages |

Decision by the author on 2026-10-16 to add them now; whether to index the
termination-benefit regulations was already an open item for Dr Azam, so the
change is reported to him at the next meeting.

## Facts about the sources (checked 2026-10-16)

- Both have a text layer; no OCR. No tables, formulas or running headers.
- Neither prints page numbers.
- Titles sit on the same line as the number: `1. Citation.`, with wrapped
  titles (`3. General provisions ... benefits` / `payment.`). Every existing
  document prints the title above the number, which the parser assumes.
- Termination regs have an ARRANGEMENT OF REGULATIONS (15 regs); the overtime
  regs have no contents page (2 regs).
- Gazette history is a footnote: `*Originally published as PU (A) 278/80 ...`
  under an underscore rule (termination) and `*Revised and published as
  PU (A) 339/1983 ...` with no rule (overtime). Neither form is recognised
  today, so it would land inside the "relevant date" definition.
- References to "section N" mean the parent Act (EA), e.g. reg. 4(1)(c)
  "section 13 (2) ... of the Act". Internal references are "regulation N".
- The JTKSM copies are retyped, with source typos ("may be death with",
  "within ant period", "business id to be taken over"). Kept verbatim.
- Currency: the termination footnote names amendments to PU(A) 520/99
  (31 Dec 1999); its LIST OF AMENDMENTS also lists PU(A) 92/11 (1 Apr 2011),
  and the text does not say whether that one is incorporated. Not resolved
  by a web search.
- Both are made under the EA, so they apply where the EA applies:
  Peninsular Malaysia and Labuan. They must never be cited to a Sabah or
  Sarawak user; the SQL region filter already guarantees this.

## Decisions

1. **Registry.** `doc_type: subsidiary` with `parent: employment_act_1955`,
   same `jurisdiction_label` as the EA. `act_number` is the revised-edition
   P.U. (A) number printed in the PDF. `as_at` is the last amendment the
   text itself says it includes (1991-10-17; 1999-12-31), with a
   `currency_caveat` for PU(A) 92/11.
2. **Labels.** `provision_label: reg.` gives citations such as
   `Employment (Termination and Lay-Off Benefits) Regulations 1980, reg. 6(1)`
   and chunk ids such as `TLB1980_r6_1`. Field names stay canonical
   (`section`, `subsection`); only their values are regulation numbers.
3. **Inline titles.** Declared per document (`inline_titles: true`), not
   detected, like `toc_pages`. The title is read from the start line, up to
   the first line ending in a full stop, and checked against the contents
   title. The "title above the number" search is switched off for these
   documents, because it would take the last line of the previous regulation
   as the next one's title.
4. **Inventory.** Termination regs use their ARRANGEMENT OF REGULATIONS
   (`toc_pages: [0, 0]`). Overtime regs declare their two regulations in the
   config (`declared_sections`), as read from the PDF; there is no contents
   page to read.
5. **Page numbers.** `page_numbers: pdf_index` sets `source_page` to the PDF
   page number (1-based). The rule "never invent a page" still holds: the
   number is the real page a reader opens in the PDF, and the config says so.
   A null page would fail validation (`source_page` is required).
6. **Footnotes.** A line starting `*Originally published` or `*Revised and
   published` starts a footnote, like `*NOTE`. Its text goes to
   `in_force_notes` of the chunks on that page by the existing rule, and
   validation rejects it in `content`.
7. **References.** For `reg.` documents, internal references are read from
   "regulation N"; "section N" is not recorded as internal, because it points
   at the EA. Recorded as a limitation, not linked.

## Out of scope

- Sabah and Sarawak equivalents (the gold items SBH-073 and SWK-033 ask
  them, so they stay external).
- Changing gold set v1. RDT-010 could later expect OT reg. 2; not done now.

## Steps (TDD)

1. Copy the PDFs to `data/raw/` with descriptive names.
2. Failing tests, then code, for: footnote markers (extract), REGULATIONS
   contents and declared inventory (toc), inline titles, `reg.` labels and
   regulation references (sections), PDF page numbering, pipeline loop, a
   corpus test per regulation, config checks.
3. Run the pipeline; check the 1,852 existing chunks are byte-identical.
4. Rebuild the index (`ml` container), smoke tests, retrieval evaluation and
   calibration; record before and after.
5. Devlog, CLAUDE.md status, `docs/chunk_schema.md`.
