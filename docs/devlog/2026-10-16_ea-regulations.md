# Development log: two Employment Act regulations indexed (16 October 2026)

Source material for the CP2 report. Follows `2026-10-10_gold-set-and-retrieval-eval.md`.
Plan: `docs/plans/2026-10-16-ea-regulations.md`.

---

## 1. Summary

The corpus now holds the two EA regulations that carry numbers the Act
leaves to subsidiary legislation: the Employment (Limitation of Overtime
Work) Regulations 1980 (104 hours a month) and the Employment (Termination
and Lay-Off Benefits) Regulations 1980 (10 / 15 / 20 days' wages per year of
service). 45 new chunks (2 + 43); 1,897 in total. The 1,852 existing chunks
are unchanged field by field, except one correction (Section 5). 334 tests
pass (27 new). Smoke checks 7/7 and 12/12.

Peninsular questions on the overtime limit, the benefit rates and the
payment deadline now retrieve the right regulation at rank 1. The cost:
two out-of-scope gold items now pass the abstention gate, so the 5-fold
out-of-scope decline rate fell from 70% to 60% (Section 7).

Decided by the author on 2026-10-16. Indexing the termination regulations
was already an open question for Dr Azam; to be reported at the next meeting.

## 2. Why these two
*Report: Corpus.*

The gold-set review (devlog 2026-10-10, data issues) found that the EA
names the overtime limit and the termination-benefit rates but does not
state them: s.60A(4)(a) and s.60J leave them to regulations. The system
could cite the empowering section and nothing more.

Both are made under the EA, so they apply where the EA applies (Peninsular
Malaysia and Labuan). The two gold items that ask these questions
(SBH-073, Sabah severance rate; SWK-033, Sarawak overtime limit) are about
Sabah and Sarawak, so they stay external: answering them needs the Sabah
and Sarawak equivalents, which are not held.

## 3. The sources
*Report: Corpus.*

| | Overtime Regulations | Termination Regulations |
|---|---|---|
| Source | JTKSM PDF | JTKSM PDF |
| Pages | 2 | 8 |
| Text layer | yes (no OCR) | yes (no OCR) |
| Regulations | 2 | 15 |
| Contents page | none | ARRANGEMENT OF REGULATIONS |
| Printed page numbers | none | none |
| Edition | revised P.U. (A) 339/1983, amended by P.U. (A) 433/1991 | revised P.U. (A) 338/1983, amendments to P.U. (A) 520/99 |

- The JTKSM copies are retyped, not AGC reprints. Their typos are kept
  verbatim: "may be death with" (reg. 13, for "dealt with"), "within ant
  period" (reg. 5(1)(a)), "business id to be taken over" (reg. 8(1)).
  Nothing is corrected on the parser's understanding (same rule as for the
  Acts).
- Currency gap: the termination footnote lists amendments to 31 December
  1999, but its LIST OF AMENDMENTS also names P.U. (A) 92/11 (in force
  1 April 2011). The text does not say whether that amendment is
  incorporated, and a web search did not find the 2011 instrument.
  `as_at` is therefore 1999-12-31 and the registry carries a
  `currency_caveat`.

## 4. Design decisions
*Report: Implementation (ingestion).*

| Decision | Reason |
|---|---|
| `doc_type: subsidiary`, `parent: employment_act_1955`, same jurisdiction label as the EA | They apply only where the EA applies. A config test enforces the match, so they can never be cited to a Sabah or Sarawak user (the SQL region filter does the rest). |
| `provision_label: reg.`: citation `..., reg. 6(1)`, chunk id `TLB1980_r6_1` | A citation must name the instrument's own unit. Schema field names stay canonical (`section`, `subsection` hold regulation numbers). |
| `inline_titles: true`, declared per document | The regulations print "2. Interpretation." on the number's line; every Act prints the title above. Declared, not detected, like `toc_pages`. The above-the-number title search is switched off for these documents: it would have taken "Regulations 1980." (the last line of reg. 1) as the title of reg. 2 (a test reproduces this). |
| Title must match the contents title (word overlap at least 0.6), ends at the first line ending in a full stop, at most three lines | Reg. 3's title wraps onto "payment."; the contents read "of lay-off", the body "or lay-off". |
| `page_numbers: pdf_index`: `source_page` is the 1-based PDF page | No page numbers are printed. The PDF page is the page a reader opens, and a null page fails validation. The rule "never invent a page" holds: the number is real, declared, and only used where nothing is printed (the function raises if a page carries a printed number). |
| `declared_sections` for the Overtime Regulations | No contents page. The two regulations are listed in the registry as read from the PDF. Coverage still means "the parser found each listed start line". |
| Footnote markers `*Originally published` and `*Revised and published` | The gazette history otherwise lands inside the "relevant date" definition (it sits at the foot of p.2, mid-definition). It goes to `in_force_notes`, like the EA notes; the validator now rejects it in `content`. |
| "section N" inside the regulations is not an internal reference | It means the EA's section N ("section 13 (2) ... of the Act"); the regulations also have a regulation 13, so the old rule would have linked the wrong provision. Internal references are read from "regulation N". |

## 5. Problems met

| Problem | Cause | Fix |
|---|---|---|
| `OT1980_r1` listed its own name as an external statute ("Overtime Work) Regulations 1980") | The external-reference pattern cannot read "(Limitation", so it captured only the tail of the title, which the self-check did not match | Skip a name that is part of the document's own name. Test added. The same bug was in `A1754_s1` ("Amendment) Act 2025", tail of its own title); it is now gone. This is the only change to an existing chunk. |
| A byte comparison of old and new `chunks.jsonl` failed | The old file held 10 stray blank lines (around line 1602); line endings are CRLF in both | Compared as records instead: 1,852 identical ids, order and fields (before the fix above). |

## 6. Evidence

- Tests: 307 before, 334 after (27 new), all passing in the `ml` container.
  New corpus tests read the real PDFs: overtime limit text, benefit rates
  across the p.4-5 break, the reg. 4(2) proviso across p.3-4, the footnote
  kept out of every chunk, titles kept out of content, typos kept,
  regulation references.
- Ingestion: `validation: clean`. EA 370, IRA 273, Sabah 627, Sarawak 435,
  Overtime Regulations 2, Termination Regulations 43, A1754 147.
- Index `459843bf28ba` (was `5d82173e1a7e`), 1,897 chunks.
- Manual reading of all 45 new chunks (citation, title, pages, notes,
  references, text ends).
- Targeted retrieval (hybrid + rerank):

| Question | Region | Result |
|---|---|---|
| Overtime limit in a month | Peninsular | OT reg. 2 at rank 1 (gate 0.995) |
| Overtime limit in a month | Sarawak | abstains (gate 0.015); regulations never retrieved |
| Overtime limit in a month | Sabah | Sabah chunks only |
| Overtime limit in a month | none | OT reg. 2 at rank 1, with Sabah and Sarawak chunks (multiple-territory flag) |
| Termination benefit after 3 years | Peninsular | TLB reg. 6(1) at rank 1 (gate 0.051, near the threshold: a long question) |
| Rate of severance pay | Sabah | abstains (gate 0.001) |
| When must termination benefits be paid | Peninsular | TLB reg. 11(1) at rank 1 |

## 7. Retrieval evaluation on gold set v1, before and after
*Report: Evaluation.* Run `data/eval/runs/2026-10-16_retrieval_report.json`
against `2026-10-10_retrieval_report.json`. Gold set v1 not edited.

| hybrid + rerank | 10 Oct | 16 Oct |
|---|---|---|
| hit@1 | 0.722 | 0.704 |
| hit@5 | 0.926 | 0.926 |
| MRR | 0.802 | 0.793 |
| recall (final) | 0.837 | 0.836 |
| abstention AUC | 0.936 | 0.918 |
| 5-fold out-of-scope declined | 70% | **60%** |
| 5-fold in-scope wrongly declined | 11% | 11% |
| threshold (in-sample) | 0.0325 | 0.0325 (unchanged, config not edited) |

Hybrid without rerank: hit@5 0.889 to 0.870, MRR 0.689 to 0.670 (RDT-008
lost its hit to TLB reg. 6(1) and 12(4)). Dense: MRR 0.683 to 0.682.

Why out-of-scope declines fell: two of the 20 out-of-scope items now pass
the gate on a near-miss match.

| Item | Question | Now matches | Gate |
|---|---|---|---|
| JPPM-013 | "What can be done by a party aggrieved by the decision of the Honorable Minister of Human Resources" | TLB reg. 15(3), "Any party aggrieved by any order or decision of the Director General ..." | 0.007 to 0.220 |
| RDT-009 | EPF unpaid for 6 months, final settlement in 45 days | TLB reg. 11(1) and 12(3), payment of termination benefits | 0.005 to 0.080 |

Both are the failure mode the gate exists for: similar wording, different
legal subject. The threshold did not move because it is set on in-scope
scores, which did not change.

Reading of the numbers:
- Gold set v1 measures the cost of the new chunks but not their benefit:
  it has no in-scope question whose answer is in a Peninsular regulation
  (the two that ask are Sabah and Sarawak). The gain is shown only by the
  targeted checks in Section 6.
- With 20 out-of-scope items, one item is 5 points. The change is two items.
- The 10 Oct figures in CLAUDE.md (70% / 11%) describe the 1,852-chunk
  corpus; the current corpus gives 60% / 11%.

## 8. Limitations

- Sabah and Sarawak equivalents are not held, so their users still get no
  overtime limit or benefit rate.
- Whether P.U. (A) 92/11 is incorporated is unknown.
- References from a regulation to an EA section are not linked to the EA
  chunk (Section 4).
- The external-reference pattern still truncates names with lower-case
  words ("Registration of Adoptions Act 1952" is recorded as "Adoptions Act
  1952"); this predates the change and also affects the Acts.
- The gazette-history note is attached to every chunk on its page (8
  chunks), by the existing rule for notes whose marker is not in a chunk.

## 9. Next steps

1. Report to Dr Azam: the two regulations, the 70% to 60% change and its
   two items, and the Sabah / Sarawak gap.
2. Add in-scope regulation questions from external FAQ sources (for
   example JTKSM's termination-benefit FAQ) in gold set v2, so the benefit
   is measured; never write them from the regulation text.
3. Find P.U. (A) 92/11 and confirm the termination text's currency.
4. The JPPM-013 and RDT-009 cases are evidence for the gate discussion
   (two-signal gate, devlog 2026-10-10 Section 9): re-run
   `scripts/exp_gate_amendments.py` on the new index before deciding.
