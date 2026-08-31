# Chunk Schema Reference

Source of truth for `src/ingestion/`. Section 1 is verbatim from the CP1
proposal (Listing 1). Section 2 is everything decided during CP2 ingestion
design — none of it existed in the original proposal, so it is an extension,
not a correction. The proposal states that "the exact fields may be refined
during implementation in CP2".

## 1. Original schema (CP1 Listing 1, EA 1955 s.59(1))

```json
{
  "chunk_id": "EA1955_s59_1",
  "statute": "Employment Act 1955",
  "act_number": "Act 265",
  "part": "Part XII",
  "part_title": "Rest Day, Hours of Work, Holidays and Other Conditions of Service",
  "section": "59",
  "section_title": "Rest day",
  "subsection": "(1)",
  "citation": "Employment Act 1955, s. 59(1)",
  "content": "Every employee shall be allowed in each week a rest day ...",
  "cross_references_internal": ["s. 37", "s. 60F"],
  "cross_references_external": ["Workmen's Compensation Act 1952 [Act 273]"],
  "jurisdiction": "Peninsular Malaysia and Labuan",
  "source_version": "as at 1 January 2023",
  "source_page": 53,
  "source_url": "https://lom.agc.gov.my/..."
}
```

- `content` is the ONLY embedded field. Everything else is metadata for
  filtering and citation, never for retrieval matching.
- `cross_references_internal` — references to other chunks within the corpus;
  resolve to a `chunk_id`.
- `cross_references_external` — references to statutes outside the corpus.
  Recorded so an answer can be flagged as depending on legislation the system
  does not hold. Never resolved to a chunk.
- Chunk boundary is the subsection. A short undivided section is one chunk,
  with `subsection` null.

## 2. CP2 extensions

### Amendment linking
Sarawak Cap. 76 and Act A1754 are indexed as two separate documents; the
principal text is never re-consolidated.

```json
"status": "in_force" | "superseded" | "deleted",
"as_at": "<consolidation date of this text>",
"amended_by": ["<chunk_id>"],       // on the principal chunk
"amends": ["<chunk_id>"],           // on the amending chunk
"amendment_status": "in_force" | "not_yet_in_force",
"commencement": "<date>" | null,
"commencement_source": "<citation to the commencement notification>"
```

Applies to Sarawak only. EA 1955, IRA 1967 and Sabah Cap. 67 are consolidated
texts (verified: Sabah cites AA1753 as the authority for its own deletions,
already reads "ninety-eight consecutive days", and applies worker->employee).

### Deleted / repealed sections
Kept as chunks, never omitted, so "what does section 92 say?" answers
"repealed by Act A1237" instead of abstaining as if it never existed.

```json
"status": "deleted",
"deleted_by": "<repealing instrument>",
"deleted_at": "<date>"
```

### Definition subsections
```json
"chunk_type": "provision" | "definition"
```
Flagged at parse time on any subsection matching `"<term>" means ...`.
Retrieval rule (M2): any `definition` chunk sharing a `section` with a
retrieved chunk is co-retrieved regardless of its own reranker score.

Rationale: Sarawak Cap. 76 s.84(1) states the maternity entitlement but
defines it only as "an eligible period"; s.84(11) supplies the number
(ninety-eight days). Without co-retrieval a chunk-level query can retrieve
(1) without (11) and be structurally unable to answer.

Provisos need no equivalent rule — a proviso stays inside the `content` of
the subsection it qualifies, per the Listing 1 s.59(1) example.

### Schedule rows
```json
"chunk_type": "schedule_row",
"row_type": "exemption" | "definition",
"row_id": "<top-level numbered item, e.g. 1A or 2>"
```
One chunk per top-level numbered item. Nested (1)-(5) and (a)-(c) conditions
stay inside that row's `content` — they are alternative ways to qualify for
the same exemption and are not meaningful alone. `row_type` distinguishes
First Schedule row 3 (defines "wages") from the exemption rows.

### Pending in-force annotations
```json
"in_force_notes": ["<verbatim footnote text>"]
```
IRA 1967 carries inline `*NOTE--` footnotes on an otherwise-current reprint,
flagging changes made by Act A1615 that have not commenced — at finer
granularity than a subsection (whole sections 12A/12B, subparagraph 62(fb),
inserted provisos, and individual words such as "three years" substituted for
"one year").

M1 scope: store the raw footnote text verbatim, one string per note. Do NOT
attempt structured extraction of old word / new word / effective date — that
is a fourth parsing problem on top of the three R4 budgets for (provisos,
omitted sections, First Schedule).

Architecturally distinct from Sarawak: there is no separate Act A1615 full
text being indexed, because the reprint already shows current law inline with
footnoted caveats. This is annotation on one chunk, not cross-document
linking.

Note these footnotes are AGC editorial annotation, not statutory text (17 in
the IRA, 14 in the EA). They must be lifted into this field during parsing and
never left inside `content`, or retrieval serves commentary as law.

### Out of M1 scope
The "Amending authority / In force from" tables in the EA and IRA (e.g. IRA
pp. 77-81) list every section against its amending instruments and dates.
Real provenance, and they would strengthen the validator, but extracting them
needs the same coordinate/table-layout parsing as the First Schedule. Revisit
at the validation-script stage in M2.
