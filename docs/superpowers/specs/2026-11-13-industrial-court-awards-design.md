# Design: Industrial Court awards in GetRight (2026-11-13)

Status: **approved by the author 2026-11-13** (22 then 19 awards, see Section 2a). A1 built the same day; the author's audit of 38 award chunks against the PDFs: **38/38 correct** (`data/eval/award_audit_sample.csv`). Still to tell Dr Azam: Section 11. Scope agreed with Dr Azam on 2026-10-16 (CLAUDE.md, Corpus): about 20 to 40 awards by topic, across regions; gold questions never written from an award; gold set v2 with v1 kept as the statute-only baseline; thresholds recalibrated on v2.

## 1. Goal

An answer can cite an Industrial Court award paragraph beside the statute, to show how the court applied the law ("In one case, the Industrial Court held ... [3]"). The statute stays the source of the rule. Core contributions unchanged: citations from chunk metadata; traceability, not verification; the gate decides on statutes; jurisdiction respected.

## 2. What the source files show (survey 2026-11-13)

| | Count |
|---|---|
| PDFs in `data/raw/court case/` | 35 (`k.pdf` is Award No. 1923 of 2025, to be renamed by the author) |
| In Bahasa Malaysia: 1822, 1824, 1825, 1845, 1869, 1876, 1897 | 7 |
| English | 28 |
| English, paragraphs not numbered (or under 6 numbers): 1815, 1823, 1826, 1828, 1829, 1877 | 6 |
| **English with numbered paragraphs** | **22** |
| Venue (English): Kuala Lumpur 21, Perak 3, Penang 2, Sabah 1 (1900), Sarawak 1 (1891) | |
| Size | 17 to 83 pages each; 35 to 170 numbered paragraphs |

Formats vary: header in English or Malay; numbering `[n]`, `n.` or `(n)`; headings differ ("Factual Backgrounds", "Issues", "Evaluation", "Findings", "Conclusion", "Decision", "Remedy"); witness evidence, submissions and quoted Malay text inside English awards; parties' addresses in the first paragraphs of some awards.

## 2a. Final selection after parsing (A1, 2026-11-13)

Closer reading during A1 changed the count from 22 to **19**: 1862 and 1919 have Malay headers and Malay reasoning (the first language check sampled an English quotation), and 1909's "1." to "18." are a list of charges, not paragraph numbers. The file `Award_1912-2025_Foong Wai Ming.pdf` holds **Award No. 1895 of 2025** (Mageswaran v Possehl Electronics). `k.pdf` was renamed by the author to `Award_1923-2025_Fatin Adilah Binti Norhadzlan.pdf`. English venues of the 19: Kuala Lumpur 12, Perak 2, Johor 1, Penang 1, Kedah 1, Sabah 1, Sarawak 1. The Sabah and Sarawak awards apply only the IRA (no Labour Ordinance named), so the A3 region rule allows them for every region.

## 3. Decisions

| # | Decision | Chosen (author, 2026-11-13) |
|---|---|---|
| A-D1 | Which paragraphs to index | **The court's reasoning only**: the court's statement of the law, its findings and its decision. Not the header, the parties' details, the evidence summaries or the submissions. |
| A-D2 | Retrieval | **Separate lane**: statutes ranked and gated exactly as now; then up to 2 award paragraphs added. Awards never push out a statute and never open the gate. |
| A-D3 | Citation form | **"Award No. 1806 of 2025, para 23"**, case name kept as published ("Siti Azmah binti Mat Taib v Trapia Malaysia Sdn. Bhd.") in the source panel. |
| A-D4 | Language | English awards only (corpus rule: official English text only; Bahasa Malaysia deferred). The 7 Malay awards are not indexed. |
| A-D5 | Unnumbered English awards (6) | **Proposed: not in the first build.** "para N" cannot be cited; a page-based citation ("p. 12") is weaker traceability. Add later only if needed to reach a topic or region. |

## 4. Parsing and chunks (milestone A1)

- PyMuPDF text, positional page furniture as for statutes; header fields parsed per format (English and the two header layouts seen).
- One chunk per numbered paragraph, quotations and sub-items kept inside their paragraph (the award equivalent of "provisos stay attached").
- Reasoning start: the first heading that opens the court's own evaluation, from a fixed list (for example "Evaluation", "Findings", "The law", "Court's findings", "Issues to be determined", "Decision"), with a **per-award override table in config, hand-checked for all 22** (as statutes have hand-fixes for rare chunks). Everything from that heading to the signature block is "reasoning".
- Chunk fields (statute schema names reused where they mean the same thing):

```json
{
  "chunk_id": "ICA2025_1806_p23",
  "doc_type": "award",
  "chunk_type": "award_paragraph",
  "statute": "Industrial Court Award No. 1806 of 2025",
  "citation": "Award No. 1806 of 2025, para 23",
  "case_name": "Siti Azmah binti Mat Taib v Trapia Malaysia Sdn. Bhd.",
  "case_number": "10/4-1123/24",
  "award_number": "1806 of 2025",
  "award_date": "2025-11-25",
  "chairman": "Zulhelmy bin Hasan",
  "venue": "Ipoh, Perak",
  "section_title": "Evaluation and findings",
  "paragraph": 23,
  "content": "...",
  "statutes_applied": ["Industrial Relations Act 1967", "Employment Act 1955"],
  "cross_references_external": [],
  "jurisdiction": "Malaysia",
  "source_version": "handed down 25 November 2025",
  "source_page": 12,
  "source_url": null
}
```

- Validation: every numbered paragraph in the reasoning part becomes exactly one chunk, numbers consecutive, none empty; header fields present; manual audit of a sample against the PDFs (as the 60-chunk statute audit).
- Expected size: roughly 22 awards x 20 to 60 reasoning paragraphs, about 600 to 1,200 chunks.

## 5. Indexing (A2)

Same table, embedder and BM25 as statutes (only `content` embedded, as CP1). New index version. Statute chunks and vectors unchanged, so statute retrieval stays identical (check: gold v1 retrieval metrics must not move).

## 6. Retrieval lane (A3)

1. Statutes: language gate, dense + BM25 filtered to statute documents, RRF, reranker, gate, expansion. Exactly as now.
2. If the gate passed: awards ranked by their own dense + BM25 + reranker, filtered by region (below); add at most 2 award paragraphs with a reranker score at or above an **award threshold calibrated on gold v2**. Same question, same chunks (deterministic).
3. Region rule (core contribution 4): an award is decided under the IRA (all Malaysia) but may apply a territory statute. An award whose `statutes_applied` includes a territory statute of another territory is excluded (a KL award applying EA s.12 is not shown to a Sabah user). Awards applying only the IRA are allowed everywhere.

## 7. Prompt and answer (A4)

- Prompt `m4-v4`: award blocks are labelled `AWARD (Industrial Court decision on one case)`. New rule: "An award shows how the Industrial Court decided one case on its facts. Do not state it as a general rule of law; say that in one case the court held or found ..., and cite it."
- Citations from metadata as now; `Citation` gains optional award fields (`case_name`, `award_number`, `paragraph`, `award_date`); API schema and frontend types regenerated.
- Checks: count answers that state an award as a rule without "in one case" wording (evaluation only).

## 8. Frontend (A5)

- Chip and Sources card labels from the API (`Award No. 1806 of 2025, para 23`), badge "Industrial Court award".
- Source panel header for awards: case name, award number, date, chairman, venue; the paragraph text; the traceability note, plus "An award is a decision on one case, not a rule that binds every employer."

## 9. Evaluation (A6)

- Gold set v2: new questions from the Q&A sources (never written from an award); an item may expect an award paragraph; v1 kept as the statute-only baseline.
- Recalibrate the statute threshold and calibrate the award threshold on v2 (5-fold, as v1). Report award-lane hit rate separately.
- Gold v1 retrieval metrics re-run: must be unchanged (statute lane untouched).

## 10. Privacy

**Author's decision (2026-11-13):** acceptable as proposed below, because GetRight is an FYP prototype that runs locally and is not published. Mention in the report that the DB now holds published award paragraphs with party names, and that a public deployment would need a privacy review.

Original proposal:

CLAUDE.md: "DB holds only statutory text." Awards are public documents but name the employee and company. Proposal: index reasoning paragraphs only (no addresses, which sit in the header and the parties' paragraph), keep names as published, change the rule to "DB holds only statutory text and published Industrial Court award paragraphs". No user data changes: still no accounts and no server-side history.

## 11. Open questions for Dr Azam

1. The privacy rule change in Section 10.
2. Regional spread: 1 Sabah and 1 Sarawak English award. Enough, or find more English awards from those branches?
3. The 7 Malay awards: confirm they stay out (English-only corpus).
4. The 6 unnumbered awards: leave out (A-D5) or cite by page.
5. Gold set v2 size and the share of award-expected items.

## 12. Milestones

A1 parser + chunks + validation + audit; A2 index; A3 retrieval lane; A4 prompt m4-v4 + citation fields + API; A5 frontend; A6 gold v2, calibration, re-run. Each with its own plan in `docs/plans/` and TDD, as M1 to M6.
