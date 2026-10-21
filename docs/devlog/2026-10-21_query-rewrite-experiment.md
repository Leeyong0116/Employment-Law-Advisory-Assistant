# Development log: offline query-rewrite experiment (21 October 2026)

Source material for the CP2 report. Follows `2026-10-21_m4-generation.md`.
Plan: `docs/plans/2026-10-21-query-rewrite-experiment.md`. Offline only:
the live pipeline, config and dev console are unchanged.

---

## 1. Why

"what if my boss havent send me any payment after 30 working days" was
declined in every region: top reranker score 0.003 to 0.010, threshold
0.0325. The law is in the corpus (EA s. 19(1): wages within seven days after
the wage period; s. 15(1); s. 91), but "boss", "send me any payment" and the
misspelling do not match the statutes' "employer" and "wages". The same
question in statute words passes (0.654 to 0.978). The dense rescue rule
from 2026-10-10 would not save it either (dense cosine 0.627, below the
highest out-of-scope 0.648). So the author proposed an LLM rewrite of the
question before retrieval.

## 2. Design (agreed with the author before running)

- **Rewrite prompt:** the author's, verbatim (Section 4 explains one added line):
  "Rewrite the user's question into formal Malaysian employment-law terms
  for searching statutes. Fix spelling. Translate Malay/Manglish words. Do
  NOT answer the question. Do NOT add facts, numbers, or legal conclusions
  that the user did not state. Output one sentence only."
- **Model settings:** Qwen3-14B (AWQ) on the HPC, temperature 0, thinking
  off, max 100 tokens. Every rewrite is cached.
- **Language gate:** stays English-first. A Malay question is translated
  by the rewrite. The answer is always generated for the user's original
  question; the rewrite is only used to search.
- **The author's constraint:** do not trade out-of-scope declines for
  in-scope recall. Every rule is tuned by 5-fold cross-validation: on
  the training folds, at least 70% of out-of-scope questions must be
  declined, and among the settings that do this, the one answering the
  most in-scope questions is chosen. All rates below are pooled over the
  held-out folds.
- **Rules compared:**

| Rule | Answer when | Chunks from |
|---|---|---|
| baseline | original score >= t | original |
| rewrite | rewrite score >= t | rewrite |
| max | max(original, rewrite) >= t | the higher one |
| or_strict | original >= t_o, else rewrite >= t_r (t_r >= t_o) | original if it passed |
| band | original >= t, else original in [low, t) and rewrite >= t | original if it passed |

- **Questions:** 54 in scope and 20 out of scope (gold v1; the 3
  external items are left out). Subsets:
  - Informal: the 5 in-scope Reddit questions (RDT-*).
  - Malay: 19 in-scope gold items asked with JTKSM's official Malay
    wording (`question_ms` in `faq_candidates_all.csv`, id `<id>-ms`),
    decided with their English item's fold. They are not counted in the
    overall rates. There are no Malay out-of-scope questions.

Code: `src/evaluation/gate_rules.py` (rules, tuning, folds; 13 tests),
`src/evaluation/rewrite.py` (prompt, cleaning, Malay variants; 10 tests),
`scripts/exp_query_rewrite.py` (stages rewrite, score, report, answers).

## 3. Results

Files: `data/eval/runs/2026-10-21_rewrite_rewrites.jsonl`, `_records.jsonl`,
`_report.json`, `_oos_answers.jsonl` (prefix `2026-10-21_rewrite`).

| Rule | Out of scope declined | In scope wrongly declined (54) | Informal (5) | Malay (19) | In scope passed with an expected chunk in the top 5 |
|---|---|---|---|---|---|
| baseline | 70% | 16.7% (9) | 60% | 100% | 43 / 54 |
| rewrite | 70% | **3.7% (2)** | **20%** | **10.5%** | 45 / 54 (7 pass without) |
| max | 70% | 13.0% (7) | 40% | 21.1% | 42 / 54 |
| or_strict | 70% | 13.0% (7) | 40% | 21.1% | 45 / 54 (2 pass without) |
| band | 70% | 13.0% (7) | 40% | 100% | 45 / 54 (2 pass without) |

- **Separation:** threshold-free AUC, in scope vs out of scope: original
  0.918, rewrite 0.941, max 0.935. The rewrite score separates the two
  groups better.
- **Retrieval is worse on the rewrite.** In-scope hit@5 is 0.926 on the
  original vs 0.833 on the rewrite; MRR is 0.793 vs 0.665. For the Malay
  variants, the rewrite gets hit@5 0.842, against 0.895 for their English
  originals. The rewrite makes the question easier to score but sometimes
  steers retrieval to other provisions. That is why the last column
  matters: "rewrite" lets 52 questions through, but 7 of them without an
  expected provision in the top 5.
- **Baseline here is 70% / 16.7%, not the reported 60% / 11%** (5-fold,
  2026-10-16). The difference is the selection rule: the author's
  out-of-scope constraint raises the threshold (fold 0: 0.080 instead of
  0.0325). All five rules here use the same rule, so they compare fairly.
- **band** cannot help Malay questions: the original is stopped by the
  language gate (score -1), so it is never inside the near-miss band.
- **Still declined under rewrite:** JPPM-005 and RDT-008. Under baseline:
  JTKSM-07, JTKSM-26, JTKSM-34, JTKSM-45, RDT-007, RDT-008, RDT-010,
  SWK-145, SWK-152.

### Out-of-scope questions that pass

Six pass under each rule (baseline, max, or_strict and band let the same
six through, all on the original wording). Every passing pair was
answered and read:

| Item | Passes under | Answer | Reading |
|---|---|---|---|
| JPPM-013 | baseline, max, or_strict, band | INSUFFICIENT_CONTEXT | says not covered |
| RDT-009 | all five | INSUFFICIENT_CONTEXT (both) | says not covered |
| SWK-086 | all five | INSUFFICIENT_CONTEXT (both) | says not covered |
| SWK-093 | all five | INSUFFICIENT_CONTEXT (both) | says not covered |
| JPPM-012 | rewrite | INSUFFICIENT_CONTEXT | says not covered |
| SWK-064 | rewrite | answered, cites A1754 s. 71(b) | **cites a wrong provision**: ties "filing fees" to the Minister's regulation-making power, then says the amount is not specified |
| SWK-069 | baseline, max, or_strict, band | answered, cites IRA s. 8(1), s. 56(1), Sarawak s. 8F (+ A1754 s. 10) | **cites wrong provisions**: the question is how to lodge a complaint at the Labour Department; the answer gives trade-union and award complaint procedures |
| SWK-092 | baseline, max, or_strict, band | answered, cites Sarawak s. 75A(4) (deleted) | **cites a wrong provision, but says so**: "No", from a deleted rule on children's minimum rates, and states that the source is deleted and not current law |

So out of the six that pass:
- **Baseline-family rules (baseline, max, or_strict, band):** 4 are
  declined by the model and 2 are answered from provisions that do not
  cover the question.
- **Rewrite:** 5 are declined by the model and 1 is answered from a
  wrong provision.

The model's `INSUFFICIENT_CONTEXT` reply is doing real work behind the
gate in both cases.

## 4. Problems met

1. **The author's prompt produced Malay.** With the prompt exactly as
   written, 82 of 97 rewrites came out in Malay, including 63 of the 77
   English questions. Qwen3 read "formal Malaysian employment-law terms"
   as Bahasa Malaysia. That contradicts the agreed design (translate to
   English; the language gate is English-first), and Malay rewrites
   cannot match English statutes in BM25.
   - **Fix:** one added line, "Write the rewritten question in English."
     The rest of the prompt is unchanged. With it, 0 of 97 rewrites are in
     Malay.
   - The first rewrites are kept as
     `2026-10-21_rewrite_rewrites_prompt-v1.jsonl`.
   - **For the report:** the experiment measures the author's prompt plus
     this line.
2. **The rewrite adds Act names.** 22 of 97 rewrites name an Act the user
   did not mention, against "do not add legal conclusions". Examples:
   - SWK-092, a Sarawak question, gets "Employment Act 1955", which does
     not apply in Sarawak.
   - SBH-019 gets "Employment Agencies Act 1985", which is not held.

   Retrieval is still filtered by region, so EA chunks cannot reach a
   Sarawak answer, but the added words can tilt BM25 and the reranker.
   Not fixed: changing the author's prompt a second time was left to
   the author. Listed in the report (`rewrite_checks.added_act_names`).
3. **Number check noise.** `added_numbers` flags 17 rewrites, mostly digits
   written as words ("3" to "three") or the year of an added Act name. On
   reading, no rewrite invents a new amount or period.
4. **Slow scoring.** The score stage took over 10 minutes while the dev
   console held the GPU at the same time.

## 5. What this suggests (for Dr Azam)

- **Rewrite only** gives the largest drop in wrong declines at the same
  70% out-of-scope decline:
  - In scope: 16.7% to 3.7%.
  - Informal: 60% to 20%.
  - Malay: 100% to 10.5%.

  But it retrieves worse (hit@5 0.926 to 0.833), so more in-scope answers
  would rest on the wrong provisions (7 vs 2).
- **or_strict** keeps the original retrieval whenever the original passes
  and uses the rewrite only for the rest:
  - It answers the same number of in-scope questions *with* an expected
    provision as rewrite-only (45), with only 2 passing without one.
  - It also helps Malay (21.1% declined instead of 100%) and informal
    questions (40% instead of 60%).
  - It is the cautious choice, and the one that best fits "a confident
    answer with wrong citations is the worst failure".
- **Either way**, adopting it changes the retrieval design and the
  language gate behaviour, so it needs Dr Azam's agreement (CLAUDE.md
  scope discipline). The threshold would need recalibrating under the
  chosen rule.

## 6. Limitations

- Small samples: 5 informal and 19 Malay in-scope questions, 20
  out-of-scope (4 per fold), and no Malay out-of-scope questions.
- One rewrite per question at temperature 0, from one model, with the
  author's prompt plus one line. No repeat runs.
- The motivating question itself is not in the gold set. A gold v2 with
  more informal and Malay questions (from forums and the bilingual FAQs)
  would test this properly.
- The out-of-scope answer reading is the author's judgement (by Claude,
  to be checked by the author), not a metric.
