# Plan A1 (2026-11-13): Industrial Court awards, parsing into paragraph chunks

Design: `docs/superpowers/specs/2026-11-13-industrial-court-awards-design.md` (decisions A-D1 to A-D5, author approved 2026-11-13: 22 English awards with numbered paragraphs, reasoning only, privacy acceptable for a local FYP).

## Goal

The 22 awards in, one validated `data/processed/award_chunks.jsonl` out: one chunk per numbered paragraph of the court's reasoning, every chunk citable as "Award No. N of 2025, para P".

## Boundaries

- Separate output file. `chunks.jsonl` (statutes) is not touched, so an index rebuild before A3 cannot mix awards into statute retrieval. A2 / A3 load the award file into the index together with the separate lane.
- No retrieval, prompt, API or frontend change in A1.

## Registry (declared, hand-checked)

`config.yaml` gets an `awards:` list, like the statute registry: citation metadata is declared, never inferred at query time.

```yaml
awards:
  raw_dir: "data/raw/court case"
  documents:
    - file: "Award_1806-2025_Siti Azmah Binti Mat Taib.pdf"
      award_number: "1806 of 2025"
      case_number: "10/4-1123/24"
      case_name: "Siti Azmah binti Mat Taib v Trapia Malaysia Sdn. Bhd."
      award_date: "2025-11-25"
      chairman: "Zulhelmy bin Hasan"
      venue: "Ipoh, Perak"
      numbering: bracket        # [n] | n. | (n)
      reasoning_from: 12        # first paragraph of the court's own evaluation (hand-checked)
```

A helper (`python -m src.ingestion.awards --survey`) prints each award's header fields, numbering style and headings with the paragraph that follows each, to fill and check the registry. The parser then cross-checks the declared award number and case number against the PDF text.

## Parsing rules (`src/ingestion/awards.py`)

1. Text per page with PyMuPDF; lines that are only a page number at the top or bottom are furniture and dropped.
2. Paragraph markers at the start of a line in the declared style. A paragraph runs from marker `k` to marker `k+1` only: numbers must go up by one, so a numbered list inside a quotation cannot split a paragraph.
3. The last paragraph ends at the signature block ("HANDED DOWN AND DATED", "Signed", the chairman's name line).
4. Lines joined into running text: a line-end hyphen before a lowercase letter is joined without a space; blank lines become paragraph breaks inside the chunk, so quotations stay readable.
5. Keep paragraphs `reasoning_from` to the last (A-D1).
6. `statutes_applied`: the statutes named in the whole award (EA 1955, IRA 1967, Labour Ordinance Sabah / Sarawak), for the region rule in A3.

Chunk fields as the design, Section 4. `chunk_id` = `ICA<year>_<number>_p<para>`, `doc_id` = `ICA<year>_<number>`, `doc_type` = `award`, `chunk_type` = `award_paragraph`, `jurisdiction` = `Malaysia`.

## Validation

Per award: declared award and case number found in the text; paragraphs 1..N all found, consecutive, none empty; `reasoning_from` within 1..N; at least 5 reasoning paragraphs; no signature-block or header text inside a chunk. Corpus: no duplicate ids; every chunk has citation, content, source_page, jurisdiction. Exit 1 on any problem.

## Tests (TDD, `tests/unit/test_awards.py`, synthetic text, no PDFs)

Marker detection in the three styles; sequential rule ignores a quoted "(4)" inside paragraph 3; hyphen joining; letter-spaced justified lines joined; signature cut; reasoning filter; chunk fields and citation label; validation catches a missing paragraph, a gap, and a wrong declared award number.

## Check against the PDFs

`award_audit_sample.csv`: a stratified sample (seed 42, about 2 paragraphs per award, 44) for the author to check content, boundaries and page numbers against the PDFs, as the 60-chunk statute audit. Claude checks a smaller sample first.

## Output

`python -m src.ingestion.awards` writes `data/processed/award_chunks.jsonl` and `award_report.json` (per award: paragraphs found, reasoning paragraphs kept, statutes applied, problems).

## Done when

Tests pass; validation clean on all 22; sample check done; devlog written.

## Status 2026-11-13: done

19 awards (not 22, see the design Section 2a), 1,143 chunks in `data/processed/award_chunks.jsonl`, validation clean. Registry in `config.yaml` `awards:` with hand-checked `reasoning` ranges (some awards have two blocks, leaving the parties' cases out) and `skips` (numbers the published award leaves out: 1812 [14], 1817 [35, 43], 1910 [90, 91], 1931 [50]). Rules added during the build, each from a real case and with a test: running headers removed by position; "1." alone on a line; "OF YEAR 2025" and "1900 / 2025"; statute names broken across lines; headings at a paragraph end moved to the next paragraphs' `section_title` (decided on the whole trailing run, after a finished sentence, one case style, never after a question, so transcript answers such as "TAMIL Ya. Setuju" stay text); a line-end hyphen kept ("post-termination", "berturut-turut"). Check: start and end of all 1,143 chunks found in their PDF text. 28 unit tests. Audit sample: `data/eval/award_audit_sample.csv` (38 rows, seed 42). **Author's audit 2026-11-13: 38/38 correct** on content, boundaries and page numbers, checked against the PDFs (Y/N columns filled, note "author check 2026-11-13").
