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

- **Rewrite prompt:** the author's, verbatim (Sections 4 and 7 explain two added lines):
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

## 3. Results (prompt v2: the author's prompt plus the English line)

Files: `data/eval/runs/2026-10-21_rewrite_rewrites_prompt-v2.jsonl`,
`_records_prompt-v2.jsonl`, `_report_prompt-v2.json`,
`_oos_answers_prompt-v2.jsonl` (prefix `2026-10-21_rewrite`). The files
without a suffix now hold the prompt v3 re-run (Section 7).

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
- **max, or_strict and band made the same decisions.** In every fold,
  the tuned rewrite threshold of or_strict equalled its original threshold
  (fold 0: 0.080, then 0.059, 0.059, 0.042, 0.042), max's threshold equalled
  baseline's, and band took its widest edge (about 0.0001, the lowest
  training score). So the three rules answer exactly the same questions,
  hence the identical 13.0% and 40%. They differ only in **which chunks**
  go to the generator:
  - max takes them from the higher-scoring wording: 14 in-scope passes use
    the rewrite's chunks, giving 42 / 54 with an expected chunk.
  - or_strict and band take the original's chunks whenever the original
    passes: only 2 passes use the rewrite, giving 45 / 54.

  The "stricter threshold" in or_strict never binds. What caps it is the
  plan's condition t_r >= t_o: the rewrite rule's own tuned threshold is
  only 0.008 to 0.011. Letting t_r go lower was not part of the plan. The
  reviewer checked it: 7.4% in-scope wrongly declined, but only 65%
  out-of-scope declined, which breaks the constraint.
- **band** as defined here cannot help Malay questions: the original is
  stopped by the language gate (score -1), so it is never inside the
  near-miss band. A live version would send language-stopped questions to
  the rewrite.
- **Still declined under rewrite:** JPPM-005 and RDT-008. Under baseline:
  JTKSM-07, JTKSM-26, JTKSM-34, JTKSM-45, RDT-007, RDT-008, RDT-010,
  SWK-145, SWK-152.

### Out-of-scope questions that pass

Six pass under each rule (baseline, max, or_strict and band let the same
six through, all on the original wording). The external items (the answer
depends on a statute not held) were added after the review: they belong to
no fold, so each fold's tuned parameters were applied to them. SWK-033
passes under every rule in all 5 folds; JTKSM-49 passes under rewrite in 2
of 5 folds; SBH-073 and the Malay JTKSM-49 never pass. Every passing pair
was answered and read:

| Item | Passes under | Answer | Reading |
|---|---|---|---|
| JPPM-013 | baseline, max, or_strict, band | INSUFFICIENT_CONTEXT | says not covered |
| RDT-009 | all five | INSUFFICIENT_CONTEXT (both) | says not covered |
| SWK-086 | all five | INSUFFICIENT_CONTEXT (both) | says not covered |
| SWK-093 | all five | INSUFFICIENT_CONTEXT (both) | says not covered |
| JPPM-012 | rewrite | INSUFFICIENT_CONTEXT | says not covered |
| SWK-064 | rewrite | answered, cites A1754 s. 71(b) | **cites a wrong provision**: ties "filing fees" to the Minister's regulation-making power, then says the amount is not specified |
| SWK-069 | baseline, max, or_strict, band | answered, cites IRA s. 8(1), s. 56(1), Sarawak s. 8F (+ A1754 s. 10) | **cites wrong provisions**: the question is how to lodge a complaint at the Labour Department; the answer gives trade-union and award complaint procedures |
| SWK-092 | all five | original: answered, cites Sarawak s. 75A(4) (deleted). Rewrite: INSUFFICIENT_CONTEXT | original: **a confident answer from a wrong, deleted provision**. It opens "No, employers cannot pay ... lower than the minimum wage", resting on a deleted rule about children's minimum rates; the caveat that the source is deleted comes only after the conclusion. Close to the worst failure in CLAUDE.md. Rewrite: says not covered |
| SWK-033 (external) | all five | original: answered, cites Sarawak s. 105A(1) and A1754 s. 35, s. 3(a)(xi). Rewrite: answered, cites s. 105(7) | original: **wrong**: presents the 45-hour weekly average of normal hours as "the limit for overtime work" (the real limit is in subsidiary legislation not held). Rewrite: **right**: the limit is set by the Minister's rules and the number is not in the sources, which matches the reference answer |
| JTKSM-49 (external) | rewrite (2 of 5 folds) | INSUFFICIENT_CONTEXT | says not covered |

So out of the six out-of-scope questions that pass:
- **Baseline-family rules (baseline, max, or_strict, band):** 4 are
  declined by the model and 2 are answered from provisions that do not
  cover the question (SWK-069, SWK-092).
- **Rewrite:** 5 are declined by the model and 1 is answered from a
  wrong provision (SWK-064).

For the external item SWK-033, the original wording gives a wrong answer
under every rule except rewrite-only; the rewrite's retrieval gives the
right "not in the sources" answer.

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
2. **The rewrite adds Act names.** 21 of 97 rewrites name an Act the user
   did not mention, against "do not add legal conclusions". Examples:
   - SWK-092, a Sarawak question, gets "Employment Act 1955", which does
     not apply in Sarawak.
   - SBH-019 gets "Employment Agencies Act 1985", which is not held.
   - SWK-093 gets a "Minimum Wages Act 1961", which does not exist.

   Retrieval is still filtered by region, so EA chunks cannot reach a
   Sarawak answer, but the added words can tilt BM25 and the reranker.
   Listed in the report (`rewrite_checks.added_act_names`). At first not
   fixed, because changing the author's prompt a second time was the
   author's call. The author then agreed to a second line (Section 7).
3. **Number check noise.** `added_numbers` flags 17 rewrites, mostly digits
   written as words ("3" to "three") or the year of an added Act name. All 17
   were read: no rewrite invents a new amount or period.
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
- **"Original first, else rewrite"** (or_strict and band here, which
  made the same decisions as max; Section 3). The gate passes if either
  wording passes at the same threshold. The chunks come from the
  original whenever the original passes, and from the rewrite only for
  the rest:
  - It answers the same number of in-scope questions *with* an expected
    provision as rewrite-only (45), with only 2 passing without one.
  - It also helps Malay (21.1% declined instead of 100%) and informal
    questions (40% instead of 60%).
  - It is the cautious choice, and the one that best fits "a confident
    answer with wrong citations is the worst failure".
  - But it keeps the original's wrong answers on SWK-033 and SWK-092,
    which rewrite-only avoids.
- **Either way**, adopting it changes the retrieval design and the
  language gate behaviour, so it needs Dr Azam's agreement (CLAUDE.md
  scope discipline). The threshold would need recalibrating under the
  chosen rule.
- **The author's choice** is "original first, else rewrite". The
  re-run with prompt v3 and its risks are in Section 7.

## 6. Limitations

- Small samples: 5 informal and 19 Malay in-scope questions, 20
  out-of-scope (4 per fold), and no Malay out-of-scope questions.
- One rewrite per question at temperature 0, from one model, with the
  author's prompt plus one line (v2) or two lines (v3). No repeat runs.
- The motivating question itself is not in the gold set. A gold v2 with
  more informal and Malay questions (from forums and the bilingual FAQs)
  would test this properly.
- The out-of-scope answer reading is the author's judgement (by Claude,
  to be checked by the author), not a metric.
- With 16 out-of-scope items in each training set, "at least 70%" means
  12 of 16 (75%) in training; held-out folds range from 50% to 100% and
  pool to 70%.
- The rule was chosen by looking at these same 74 items. Cross-validation
  protects the thresholds, not the choice between five rules.

## 7. Follow-up: the Act-name line (prompt v3)

**The author's decisions after reading Sections 3 to 5:**
- The preferred rule is "original first, else rewrite" (or_strict here).
  It goes to Dr Azam as a proposal and is not adopted.
- Keep the English line.
- Add a second line to the rewrite prompt: "Do NOT name an Act or
  section that the user did not state." It was added test first.

All four stages were re-run. The prompt v2 files are kept with the suffix
`_prompt-v2`, and the files without a suffix are now prompt v3.

**The rewrites follow the prompt better.**
- **Act names the user did not state:** down from 21 to 0. The check still
  lists 4 (JTKSM-10, JTKSM-45 and their Malay variants), but those
  questions say "this act" in lower case, which the check's pattern
  misses. They are not additions.
- **Numbers flagged:** down from 17 to 8.
- **Language:** no Malay output.
- **How much changed:** 69 of 97 rewrites are worded differently.
- **One mistranslation:** JTKSM-45-ms names the "Department of
  Occupational Safety and Health" where the question means JTKSM.

**Gate results** (5-fold, same selection rule as Section 3):

| Rule | Out of scope declined | In scope wrongly declined (54) | Informal (5) | Malay (19) | In scope passed with an expected chunk in the top 5 |
|---|---|---|---|---|---|
| baseline | 70% | 16.7% (9) | 60% | 100% | 43 (2 pass without) |
| rewrite | 75% | 7.4% (4) | 20% | 15.8% | 44 (6 pass without) |
| or_strict (original first) | 70% | 11.1% (6) | 40% | 21.1% | 44 (4 pass without) |

- **Compared with prompt v2:**
  - rewrite: 3.7% (2), with 45 passing on an expected chunk and 7 without.
  - or_strict: 13.0% (7), with 45 passing on an expected chunk and 2 without.
- **max and band** again make the same decisions as or_strict. As in
  Section 3, band never helps the Malay questions.
- **Retrieval on the rewrite improves:**
  - English hit@5 rises from 0.833 to 0.852, and MRR from 0.665 to 0.711.
  - Malay hit@5 falls from 0.842 to 0.789.
  - The original stays at 0.926 and 0.793.
  - Rewrite AUC is 0.939.

**What "original first" rescues.** The rewrite is used only when the
original wording fails the gate. The in-scope questions it rescues were
answered and read:

- **JTKSM-26 (both prompts):** correct. It gives the sick leave table
  from EA s. 60F(1).
- **RDT-010 (both prompts):** partly right. It states the
  one-and-a-half rate for overtime from the s. 60A(3) definition, which
  reached the context by definition expansion and not in the top 5. The
  rewrite ("Is the employer's adjustment of working hours and overtime
  pay in accordance with ...") dropped the hours the user gave.
- **JTKSM-07 (v3 only):** a **confident wrong answer**.
  - The model said "Yes, high-salaried employees are also eligible for
    overtime pay", citing the s. 60A(3) definition of overtime.
  - The reference answer is the opposite. Employees earning more than
    RM4,000 a month (except manual workers) are not entitled, under the
    First Schedule.
  - The rewrite's retrieval found the overtime rule but not the First
    Schedule.
  - Under prompt v2 this question was declined.
  - The question depends on context ("Does this mean ..."), because it
    comes from an FAQ series on the 2023 amendment.

**Out-of-scope answers.**
- **"Original first" passes the same six out-of-scope questions as
  before**, all on the original wording. Its answers are therefore the
  same under both prompts: SWK-069 and SWK-092 wrong, and the external
  SWK-033 wrong.
- **Rewrite-only** now also passes SWK-089 and the external SBH-073, and
  its answers are worse than under v2:
  - **SWK-089** ("Who is eligible to receive the minimum wage?"):
    **answered wrongly** from A1754 s. 73 and the IRA First Schedule. It
    presents the Ordinance's coverage rule as minimum-wage eligibility.
  - **SWK-092:** now answered, where v2 gave INSUFFICIENT_CONTEXT. It
    opens "No, employers cannot ..." from the deleted s. 75A(4), and
    only then says the source is deleted.
  - **SWK-093:** answered with a hedge. It says the penalty is not
    directly specified, then cites the general wage-offence fines
    (s. 130D, A1754 s. 60).
  - **SWK-033 (external):** now partly wrong. It says the limit is set by
    the Minister's rules, which is right, but then gives the 45-hour week
    as if it were the overtime limit. Under v2 this answer was right.
  - **SBH-073, JPPM-013 and RDT-009:** INSUFFICIENT_CONTEXT.

**What this shows.**
- **The line fixed what it targeted.** There are no invented Act names,
  and retrieval on the rewrite is better.
- **One prompt line changes outcomes.** One more prompt line moved the
  gate results by one or two questions in each direction and visibly
  changed the rewrite-only answers. The rewrite path is sensitive to
  prompt wording. With these sample sizes, a better prompt cannot be
  told apart from noise.
- **"Original first" is less exposed.** Its out-of-scope behaviour does
  not depend on the rewrite prompt at all, because those questions never
  reach the rewrite.
- **Its risk sits in the rescued questions.** Under v3, one of the three
  rescued questions (JTKSM-07) became a confident wrong answer. If the
  rule is adopted, the rescued questions should be reported separately
  in the RAGAS and manual citation checks, and a gold v2 should hold more
  of them.
- **The author's preference stands:** "original first, else rewrite"
  with prompt v3, pending Dr Azam.
