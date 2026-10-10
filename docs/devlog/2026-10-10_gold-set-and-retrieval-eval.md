# Development log: gold set v1 and first retrieval evaluation (10 October 2026)

Source material for the CP2 report. Follows `2026-10-10_m3-retrieval.md`
(same day, earlier session).

---

## 1. Summary

A gold set of 77 externally sourced questions was built, checked against
the corpus provision by provision, and used for the first evaluation of
the three retrieval modes. Hybrid + rerank is best on every retrieval
metric (hit@5 0.926, MRR 0.802, recall 0.837) and on abstention (AUC
0.936; 5-fold cross-validated: 70% of out-of-scope questions declined, 11%
of in-scope questions wrongly declined). The abstention thresholds in
`config.yaml` are now calibrated on the gold set. Checking the gold set
also exposed five data issues in the M1 output (Section 6). 307 tests
pass; retrieval smoke 12/12.

Answer metrics (faithfulness, answer relevancy) are not measured yet: they
need generated answers (M4) and a judge model.

## 2. Building the gold set
*Report: Evaluation (dataset).*

### 2.1 Sources (all external; none written while reading the statutes)

| Source | Questions | Notes |
|---|---|---|
| JTKSM, *Soalan-Soalan Lazim Akta Kerja 1955 (Pindaan) 2022* (PDF, Malay) | 75 | Official; Employment Act amendments; answers included |
| CentralHR English translation of the same FAQ (30 Aug 2023) | (same 75) | Used as a translation aid only; does not credit JTKSM |
| JPPM (Department of Industrial Relations) EMS FAQ web page | 13 | Industrial Relations Act 1967 |
| JTK Sarawak FAQ web page | 191 | Two FAQs on one page: an older general FAQ (95) and an FAQ on the Act A1754 amendments (96) |
| JTK Sabah FAQ web page | 118 | Labelled as on the Sabah amendment Act 2025 |
| Reddit r/malaysia posts | 6 posts, 10 questions | Real user wording; condensed by the author, wording kept |

Candidate pool: 403 questions (`data/eval/faq_candidates_all.csv`). Web
pages were saved as accessed (`data/raw/faq_web/*_2026-10-10.html`);
forum posts are copied verbatim in `data/raw/forum_questions.md`.

One forum post was removed with its 4 questions: its link could not be
verified (Reddit blocks automated access, and the link the author found
belonged to a different post already in the set). Questions without a
verifiable source are not used.

### 2.2 Translation check
The CentralHR translation was compared with the Malay original question
by question. Three translation errors were corrected in the candidate
list: Q13 ("disengajakan" is *wilful* breach, not *agreed*), Q33 (the
question asks whether the *employee's* consent is needed; the translation
reversed it), Q49 (the order is the Employment (Exemption) Order 2012, not
a housing order). A fourth suspected error (Q57) turned out to be in the
Malay original itself, which calls "apprenticeship" a person; it was not
"corrected" and is flagged instead.

### 2.3 Selection
Rules, applied before any system output was seen:
- Dropped: "why" policy questions, commencement and transition questions,
  administrative procedure, and near duplicates across the three state
  FAQs (one region kept per topic).
- Out-of-scope items taken from the same official pages where they cover
  instruments the corpus does not hold (Minimum Wages Order, Private
  Employment Agencies Act 1981, judicial review, SOCSO/EPF) or
  administrative facts no statute states (filing cost, office address,
  licensing age limit, a court ruling).
- Stratified by region, topic, difficulty and scope (CLAUDE.md).
- Questions were chosen by whether the corpus contains the answer, never
  by running the system: choosing questions the system already answers
  would bias the evaluation.

### 2.4 Checking each question against the corpus
For every selected question the provisions holding the answer were found
in `chunks.jsonl` by text search and read in full. Each item records the
expected chunk ids and one of these outcomes
(`data/eval/gold_review.json`):

| Outcome | Items | Meaning |
|---|---|---|
| verified | 39 | Source answer fully supported by the expected provisions |
| partial | 7 | Only part supported; reference answer trimmed to that part |
| inference | 4 | Answer follows from the text but is not stated in it |
| corrected | 4 | Source answer wrong or outdated; reference rewritten from the statute |
| external | 3 | Answer depends on an instrument the corpus does not hold |
| out_of_scope_confirmed | 20 | Corpus searched; no provision answers it |
| excluded | 2 | Source answer goes beyond the statute; replaced |

The four corrections:
- SWK-028: the older Sarawak FAQ says 60 days' maternity leave; Act A1754
  s.24 substituted s.84(11): not less than ninety-eight consecutive days.
- SBH-078: the Sabah FAQ gives a fine of up to RM10,000 for late wages;
  the current s.130J says fifty thousand ringgit (its section number,
  130J(c), is right).
- SBH-094: the Sabah FAQ cites s.119, which is deleted ("[Deleted by
  AA1238]"); the licence requirement is s.118(1) and the offence s.130L.
- SWK-184: the FAQ answers as if housing Part IVa were in force; A1754
  s.52 has not commenced.

The two exclusions: JTKSM-30 (that break time is outside the 45-hour week
is not in s.60A) and SWK-120 (s.19B says nothing about the employee's
consent). They were replaced by JTKSM-44 and SWK-044.

15 reference answers were rewritten: the 4 corrections, the 7 partial
items (4 of them forum questions, which have no reliable source answer),
the fifth forum question (RDT-006) and the 3 external items. 5 questions
were reworded minimally to stand alone (originals kept in
`question_original`). The author delegated the
review to Claude; the 15 rewritten references are still to be read by the
author.

### 2.5 Result: gold set v1 (`data/eval/gold_set.jsonl`)

| | Items |
|---|---|
| In scope | 54 (Peninsular 19, IRA / all Malaysia 6, Sarawak 13, Sabah 11, no region 5) |
| External instrument | 3 |
| Out of scope | 20 |
| Total | 77 |

In-scope topics: leave 15, other 11, wages 8, termination 7, hours 6,
dismissal 5, coverage 2. Difficulty: single provision 41, several 13.
Meets CLAUDE.md: 60 to 80 items, at least 40 in scope and 20 out of scope.

Fields per item: question (and original if reworded), region, scope
class, topic, difficulty, reference answer and whether it was rewritten,
expected chunk ids and their citations, check outcome, source, notes.

## 3. Evaluation method: where every number comes from
*Report: Evaluation (method).*

Command (inside the ML container, database running):
```
docker compose run --rm ml python -m src.evaluation.retrieval_eval
```
Code: `src/evaluation/retrieval_eval.py`, `src/evaluation/calibration.py`.
Output: `data/eval/runs/2026-10-10_retrieval_records.jsonl` (one record
per mode and question: ranked top 5, final result after expansion, gate
score) and `data/eval/runs/2026-10-10_retrieval_report.json` (all
metrics). Retrieval is deterministic, so rerunning gives the same records.

Every question is retrieved in each of the three modes with the
abstention gate off (`gate=False`), so every question gets chunks and a
gate score.

| Number | Function | Definition | Origin |
|---|---|---|---|
| hit@1, hit@5 | `hit_at_k` | Share of questions with at least one expected chunk in the top 1 / top 5 | Standard IR metric |
| MRR | `reciprocal_rank` | Mean of 1 / rank of the first expected chunk (0 if none in the top 5) | Standard IR metric (TREC QA, Voorhees 1999) |
| recall_top5 | `recall` | Expected chunks found in the top 5, divided by expected chunks | Standard |
| recall_final | `recall` | Same, on the final result (top 5 + expansion) | Standard; shows what expansion adds |
| RAGAS ID precision / recall | `ragas_id_scores` | `IDBasedContextPrecision` / `IDBasedContextRecall` from the ragas library: overlap of retrieved and expected chunk ids, divided by retrieved / expected | RAGAS (Es et al., EACL 2024), ragas 0.4.3 |
| AUC | `calibration.roc_auc` | Probability that an in-scope question has a higher gate score than an out-of-scope one (ties half) | ROC AUC, Mann-Whitney form |
| Threshold | `calibration.select_threshold` | Highest threshold that declines at most 10% of in-scope questions | Rule fixed before the runs (plan 2026-10-10, 7a) |
| Decline rates | `calibration.rates` | Share of out-of-scope / in-scope questions with gate score below the threshold (equal passes) | |
| 5-fold rates | `kfold_abstention` | Stratified, deterministic 5-fold: threshold chosen on four folds, applied to the fifth, counts pooled | Standard k-fold cross-validation |

Only the two RAGAS figures come from the ragas library; the rest are the
project's own implementations of standard definitions, unit tested
(`tests/unit/test_retrieval_eval.py`, `test_calibration.py`). Check on the
implementation: recall_final and the RAGAS ID recall are identical in all
three modes (same definition, independent code).

Gate score per mode: dense = top cosine similarity; hybrid = best cosine
among its top 5 (RRF scores carry no relevance signal); hybrid + rerank =
top reranker score. External items are reported apart from the
in-scope / out-of-scope comparison.

**How the threshold 0.0325 arises (hybrid + rerank).** 54 in-scope
questions, budget 10%, so at most 5 may be declined. Sorted by gate
score, the lowest are JTKSM-07 0.0095, RDT-010 0.0132, RDT-008 0.0180,
JTKSM-45 0.0181, SWK-145 0.0286, then JTKSM-26 0.0325. The threshold is
the sixth score, 0.0325: the five below it are declined (9%). Of the 20
out-of-scope questions, 5 score at or above it and would be answered
(SWK-093 0.628, SWK-086 0.262, SWK-069 0.103, SWK-092 0.059, SBH-033
0.042), so 15 (75%) are declined.

**Why 5-fold.** Choosing the threshold and measuring decline rates on the
same 74 items is optimistic. In 5-fold cross-validation each item is
tested once by a threshold chosen without it. Five folds leave four
out-of-scope items per fold; more folds would leave too few. The fold
thresholds were 0.0325, 0.0286, 0.0325, 0.0325 and 0.0419: stable. The
cross-validated rates are the ones to report; the in-sample threshold is
the one the running system uses.

**Dependency note.** ragas 0.4.3 fails to import with
langchain-community 0.4.x (a module it imports was removed); pinned
langchain-community 0.3.31. Both pins in `requirements.txt`.

## 4. Results
*Report: Results.*

### 4.1 Retrieval (54 in-scope questions, gate off)

| Mode | hit@1 | hit@5 | MRR | recall top 5 | recall final | RAGAS ID precision | RAGAS ID recall |
|---|---|---|---|---|---|---|---|
| Dense | 0.611 | 0.815 | 0.683 | 0.723 | 0.751 | 0.180 | 0.751 |
| Hybrid | 0.556 | 0.889 | 0.689 | 0.755 | 0.774 | 0.190 | 0.774 |
| Hybrid + rerank | **0.722** | **0.926** | **0.802** | **0.810** | **0.837** | **0.212** | **0.837** |

Misses (no expected chunk in the top 5): dense 10, hybrid 6, hybrid +
rerank 4 (JTKSM-07, JTKSM-45, RDT-006, SBH-043).

Hybrid + rerank by group (recall, top 5 / final):

| Group | n | hit@5 | recall top 5 | recall final |
|---|---|---|---|---|
| Sarawak | 13 | 1.00 | 0.92 | **1.00** |
| Sabah | 11 | 0.91 | 0.91 | 0.91 |
| Peninsular | 19 | 0.90 | 0.82 | 0.84 |
| IRA (all Malaysia) | 6 | 1.00 | 0.83 | 0.83 |
| No region | 5 | 0.80 | 0.24 | 0.24 |
| Single provision | 41 | 0.95 | 0.89 | 0.92 |
| Several provisions | 13 | 0.85 | 0.56 | 0.59 |

Expansion added an expected chunk for JTKSM-35 (the hourly-rate
definition) and for SWK-145 and SWK-152 (the A1754 amending sections):
Sarawak recall rises from 0.92 to 1.00 through the amendment links alone.

### 4.2 Abstention (54 in-scope vs 20 out-of-scope, budget 10%)

| Mode | AUC | Threshold (all items) | Out declined (all) | In declined (all) | Out declined (5-fold) | In declined (5-fold) |
|---|---|---|---|---|---|---|
| Dense | 0.893 | 0.5555 | 60% | 9% | 55% | 13% |
| Hybrid | 0.905 | 0.5555 | 65% | 9% | 60% | 13% |
| Hybrid + rerank | **0.936** | 0.0325 | 75% | 9% | **70%** | **11%** |

No gold question was stopped by the language gate. External items' gate
scores (hybrid + rerank): JTKSM-49 0.0041, SBH-073 0.0012, SWK-033 0.0998.

The thresholds in `config.yaml` were updated to the in-sample values
above (dense and hybrid 0.5555, hybrid + rerank 0.0325), replacing the
provisional dev-list values.

## 5. Discussion points
*Report: Discussion.*

1. **Hybrid + rerank is best on every metric**, the quantitative case for
   the CP1 design. On the 25-question dev list dense and reranker gates
   looked equal (AUC 0.967 vs 0.960); on the 74-item gold set the reranker
   separates better (0.936 vs 0.893). Small sets cannot rank methods.
2. **Amendment links matter**: two Sarawak answers need the amending
   section, which the reranker alone did not place in the top 5.
3. **Multi-provision questions are the weak point** (recall 0.59).
4. **Near-miss out-of-scope questions are the hardest to decline.**
   "What are the penalties for employers who do not pay the minimum
   wage?" scores 0.628 because the Ordinance's penalty sections match the
   words; the Minimum Wages Order itself is not held.
5. **A correctly retrieved answer can still be declined.** SWK-145 (recall
   1.00) scores 0.0286 and is declined at 0.0325: the answer needs the
   principal text and its amendment together, and the cross-encoder
   scores each chunk alone.
6. **Reading the metrics**: RAGAS ID precision is low by construction (5
   to 12 chunks returned, 1 to 3 expected) and only compares modes; the
   no-region recall is low because those items expect equivalent
   provisions from three statutes, which a top 5 cannot hold (hit@5 0.80
   is the fairer figure).

## 6. Data issues found while checking the gold set
*Report: Implementation (validation), Limitations.*

1. **Misleading citation labels.** A subsection containing a mid-sentence
   definition is named after the definition: EA s.37(1) (return to work
   during maternity leave) is cited "s. 37(1), definition of 'children'".
2. **"Superseded" applied too widely.** A1754 s.34 changes only s.105(1)
   and (10), but 13 chunks of s.105 are marked superseded; A1754 s.24
   changes four subsections of s.84, but 11 chunks are. Unchanged text
   (e.g. the overtime rate, s.105(6)) is labelled outdated.
3. **Labuan.** EA s.1(2) reads "This Act shall apply to Peninsular
   Malaysia only". The extension to Labuan (CLAUDE.md, config) comes from
   an instrument not in the corpus.
4. **Rates held outside the corpus.** Termination-benefit rates (EA
   s.60J, Sabah s.104F, Sarawak s.105F only empower rules) and the monthly
   overtime limit are in subsidiary legislation not held, and
   `cross_references_external` is empty for these sections, so the system
   cannot say the answer depends on them.
5. **Source quality.** The Sabah FAQ cites section numbers copied from the
   EA and Sarawak FAQs (13(2), 105EA, 114); the older Sarawak FAQ predates
   A1754.

Errors corrected during the session (recorded for honesty): the RM4,000
threshold was first reported as absent from the EA (it is written in
words, "four thousand ringgit", First Schedule para. 1A); a search that
covered EA chunks only briefly suggested "ninety-eight" was absent from
A1754 (it is in A1754 s.24); a suspected translation error in Q57 was in
the Malay original.

## 7. Limitations of this evaluation

- The gold set was checked by Claude with the author's delegation; the 15
  rewritten reference answers still need the author's reading.
- Expected chunks reflect one careful reading of the corpus; another
  reader might add a provision for multi-provision questions.
- Gold set v1 must not be edited after seeing answer-level results except
  for documented errors.
- Faithfulness and answer relevancy, and the LLM-judged context metrics,
  wait for M4 and a judge model.

## 8. Next steps

1. Author reads the 15 rewritten reference answers.
2. Ask Dr Azam: 5-fold calibration and the 10% budget; keep JTKSM-68
   (inference); termination-benefit regulations in or out of the corpus;
   the Labuan basis; judge model for RAGAS.
3. Fix data issues 1 and 2 (citation labels, superseded scope); add
   external references for s.60J, s.104F, s.105F.
4. M4: prompt and generator over `RetrievalResult`, then full RAGAS on the
   gold set.

## 9. Follow-up: why is SWK-145 declined although retrieval was right?
*Report: Discussion (abstention), Future work.*

SWK-145 (Sarawak: may an employer move to five days of nine hours to meet
the 45-hour week?) has recall 1.00 but a gate score of 0.0286, below the
threshold 0.0325. Diagnosis script: `scripts/exp_gate_amendments.py`.

| Hypothesis | Test | Result |
|---|---|---|
| H1 bug: sliding window cuts the proviso | Token count and windows of SWK76_s105_1 | 308 tokens, one window, proviso (ac) "nine hours" included. Not a bug |
| H2 bug: gate reads the wrong score | Rescore the ranked list | Recorded 0.0286 = top reranker score now. Not a bug |
| H3 outdated "forty-eight" contradicts the question's "45" | Replace forty-eight with forty-five (diagnostic only) | 0.0285 -> 0.0288. Not the cause |
| H4 amending chunk has no context | Score A1754 s.34 alone; amendment + principal joined | 0.0005 alone; 0.0079 joined (lower). True, but not the main cause |

Control: the same rule where the text already says forty-five scores
almost as low (EA s.60A(1) 0.048, Sabah s.104(1) 0.036). The cause is
the question type, not Sarawak or the amendment design.

**Systematic pattern.** Over the 50 in-scope items whose top 5 holds an
expected chunk, gate score falls with question length (Spearman -0.29):
median 0.908 for questions of up to 15 words (n = 21), 0.117 for over 25
words (n = 14). Long scenario questions ("may the employer do X?") need
reasoning from the provision, and the cross-encoder gives them low
absolute scores even when the right provision is first. Three of the five
in-scope items declined in-sample are of this kind with correct retrieval
(RDT-010, RDT-008, SWK-145); the other two (JTKSM-07, JTKSM-45) had no
expected chunk in the top 5, so declining them is defensible.

**A possible fix, evaluated offline (not adopted).** The three wrongly
declined items all have dense top cosine >= 0.654, above every
out-of-scope item (max 0.648). Rule tested with the same 5-fold folds:
answer if reranker >= its threshold (usual rule) OR dense cosine is above
the highest out-of-scope dense score in the training folds.

| Gate rule (5-fold) | Out-of-scope declined | In-scope wrongly declined |
|---|---|---|
| Reranker only (current) | 70% | 11% |
| Reranker OR dense rescue | 70% | **6%** |

It rescues exactly RDT-008, RDT-010 and SWK-145 and lets no extra
out-of-scope question through. Caveats: 20 out-of-scope items is few; the
dense rescue threshold rests on the single highest out-of-scope training
score, so one new near-miss question could move it; and CLAUDE.md defines
the gate as a reranker-score threshold, so adopting a two-signal gate is a
design change that needs the supervisor's agreement. Recorded as a
proposal and as a discussion point: retrieval can be right while the
abstention decision is wrong.
