# Plan: M3 retrieval pipeline

Status: implemented 2026-10-10 (devlog `docs/devlog/2026-10-10_m3-retrieval.md`).
Approved 2026-10-10: decisions 1 to 5 as recommended, plus the user's
additions: fair abstention comparison across modes, a total chunk cap,
`multiple_jurisdictions`, a mixed-language smoke check, and checking the
long chunks in the reranker experiment. Where implementation differed from
this text, the text below has been corrected and the devlog says why.

## Goal

One function that takes an English question and a region and returns either
a ranked, labelled set of chunks ready for the prompt, or a typed abstention.
M4 (generation) consumes this output and nothing else.

```
question, region
  -> language gate          (not English: abstain, no retrieval)
  -> dense top 20 + BM25 top 20, region filter in SQL / in BM25
  -> RRF fusion, top 20
  -> bge-reranker-large, top 5
  -> abstention gate        (top reranker score < threshold: abstain)
  -> expansion              (amendment links, same-section definitions)
  -> RetrievalResult
```

Already built and tested (2026-10-09): `fusion.py` (RRF), `rerank.py`.
Out of scope for M3: prompt, generator, citation rendering, API, RAGAS.

## Facts from the data that shape the design

| Fact | Consequence |
|---|---|
| 167 chunks carry `amended_by` (138 superseded, 29 deleted by A1754), all links resolve | Forward link following is a lookup, no search. |
| 71 A1754 chunks carry `amends`, up to 13 targets each | Reverse following needs a cap. |
| 202 definition chunks: 160 in the s.2 interpretation sections, 42 in other sections (at most 6 per section) | "Same-section definitions" is safe outside s.2; inside s.2 it would pull up to 48 definitions. |
| 216 placeholder chunks ("(Omitted).", "(Deleted by Act A1026).") | Dense noise for nonsense queries (devlog 2026-10-09, obs. 2). |
| 165 `not_yet_in_force` chunks | Must stay retrievable ("is the housing rule in force?"), but labelled. |
| 27 chunks over 350 words (12 in A1754) | bge-reranker-large reads 512 tokens; the end of these chunks is not scored. Measured in task 1; handled by a sliding window (Section 3). |

## Components

### 1. Language gate (`src/retrieval/language.py`)

- `lingua-language-detector`, restricted to English, Malay, Indonesian,
  Chinese and Tamil (the realistic inputs in Malaysia). Deterministic,
  works on short text better than `langdetect`. Runs in the ML container.
- Abstain with `reason: "language"` only when the detector is confident the
  query is not English. Queries with fewer than 3 alphabetic words pass
  ("EPF", "section 60E"), because detection on them is unreliable; the
  reranker gate catches nonsense like "nihao".
- Mixed English and Malay is normal in Malaysia ("Can I claim cuti
  sakit?"). Such a query must pass. As implemented: whole-text confidence
  could not do this (that question gets English 0.16, pure Malay 0.00 to
  0.02), so the gate counts words. A word is English if it is an English
  function word or lingua scores it English alone; the query passes when at
  least 30% of its words are English. Measured on 27 questions: English and
  mixed 0.4 and above, Malay 0.17 and below. Mostly non-Latin text (Chinese,
  Tamil) is stopped at any length.
- Why it is required: BM25 has zero overlap on non-English input and the
  dense side returns its nearest junk (CLAUDE.md).

### 2. Retrieval with placeholder handling

- Dense: exclude placeholder chunks (`parse_rule` in `placeholder`,
  `range_placeholder`) in the SQL `WHERE`. BM25 keeps them, so "section 92"
  still finds "(Deleted by Act A1026)." through the citation text.
- Region filter as now (`config.retrieval.regions`). Region `None` searches
  all jurisdictions (see decision 5).

### 3. Reranking

- Existing `Reranker`, rerank pool 20, keep top 5.
- Reranker input: citation + section title + content (decision 2, settled
  by the experiment below).
- Sliding window for chunks longer than the reranker's 512 tokens: the
  passage is split into overlapping windows that each fit next to the query,
  each window starts with the citation and title, and the chunk's score is
  the best window's score. Only about 27 chunks need more than one window.

**Experiment result (task 1, `scripts/exp_rerank_input.py`, 2026-10-10).**
Part A, first expected chunk in the reranked pool of 20, content only vs
citation + title + content:

| Query | Content | Cite + title + content |
|---|---|---|
| "section 60E" | #3, 0.018 | #2, 0.814 |
| "what does section 92 of the Employment Act say" | #17, 0.004 | #2, 0.155 |
| "section 20 of the Industrial Relations Act" | #14, 0.058 | #4, 0.723 |
| "section 24 deductions from wages" | #4, 0.641 | #1, 0.981 |
| "how much notice must my employer give ..." | #2, 0.755 | #1, 0.977 |
| "can my employer dismiss me for joining a union" | #2, 0.773 | #1, 0.799 |
| 6 other in-scope queries | same rank (#1), scores within 0.06 | |
| 4 out-of-scope queries, top score | at most 0.003 | at most 0.000 |

Part B: of the 27 chunks over 350 words, 25 (content) and 27 (with
citation and title) exceed the 512-token limit. With a query taken verbatim
from the cut-off tail, the truncated input scores under 0.5 while a window
containing the tail scores at least 0.5 in 12 and 15 of them. Example: EA
s.37(1) "children" definition chunk, whose tail holds the "eligible period"
definition (truncated 0.201, window 0.994). Hence the sliding window.

Two in-scope questions score low even at their best: "section 92" (0.155;
EA s.92 is a short in-force offence section, not a deleted one as first
assumed) and "can my employer cut my salary" (0.179). Both must be in the
calibration questions, or the threshold will be set above them.

### 4. Abstention gate (in `src/retrieval/pipeline.py`; arithmetic in `src/evaluation/calibration.py`)

- Abstain with `reason: "low_score"` if the top reranker score is below
  `retrieval.abstention_threshold`. Expansion chunks never count toward the
  gate: they are added because of a link, not because they match.
- Calibration tool `scripts/calibrate.py`: runs retrieval over a labelled
  question file (`in_scope: true/false`), records the top reranker score,
  sweeps thresholds, and prints for each: % out-of-scope correctly declined,
  % in-scope wrongly declined. Same file format as the gold set.
- Threshold value: see decision 3.
- The abstention response lists the statutes held (from `config.yaml`), so
  M4 can show the out-of-scope notice without another lookup.

### 5. Expansion (`src/retrieval/expand.py`)

All expansion is metadata lookup (CLAUDE.md: cross-references as metadata,
not a graph). Each added chunk records why it is there.

| Rule | Trigger | Adds | Cap |
|---|---|---|---|
| Forward amendment | retrieved chunk has `amended_by` | the A1754 chunk(s) | none (at most 2 per chunk in the data) |
| Reverse amendment | retrieved A1754 chunk has `amends` | the principal chunks it amends | 3, in document order (decision 4) |
| Same-section definition | retrieved chunk in section X, X is not the interpretation section | definition chunks of the same document and section X | none (at most 6 in the data) |

- **Total cap: 12 chunks** (`retrieval.max_chunks`), the top 5 included,
  so at most 7 expansion chunks. When the cap is reached, expansions are
  added in priority order: forward amendment links first (without them the
  answer comes from repealed text), then same-section definitions, then
  reverse amendment links. Within one rule, chunks follow the rank of the
  chunk that triggered them. The result records how many were dropped
  (`expansions_dropped`), so a cap that bites is visible, not silent.
- Superseded chunks stay in the context, labelled `superseded` with
  `superseded_by`. Removing them would lose the unamended subsections that
  an "amend subsection (1) by substituting ..." chunk depends on. M4's prompt
  rule (lead with in-force wording) uses these labels.
- Not followed in M3: `cross_references_internal` (443 references in 254
  chunks). Passed through as metadata. One-hop following is an option to
  measure later if the gold set shows misses.
- s.2 definitions are not co-retrieved by term matching in M3. Common terms
  ("employee", "wages") appear in almost every chunk, so a naive rule adds
  noise to every answer. Revisit with gold-set evidence.

### 6. Result schema (`src/retrieval/schema.py`, Pydantic)

```
RetrievalResult
  query, region, jurisdictions_searched
  jurisdictions_found  jurisdictions of the returned chunks
  multiple_jurisdictions  true when region is None and the chunks come from
                       more than one territory (Peninsular and Labuan,
                       Sabah, Sarawak). "Malaysia" (IRA) applies everywhere
                       and does not count. Tells M4 to say the answer
                       differs by territory instead of blending them.
  mode                 "dense" | "hybrid" | "hybrid_rerank"
  abstained: bool
  abstain_reason       null | "language" | "low_score" | "no_candidates"
  detected_language
  gate_score, threshold   the score the gate used (see Section 7)
  expansions_dropped
  statutes_held        (for the abstention notice)
  chunks: list[RetrievedChunk]
  index_version

RetrievedChunk
  chunk_id, citation, statute, section, subsection, section_title,
  jurisdiction, status, content, source_page, source_url, source_version,
  in_force_notes, cross_references_external,
  score                the mode's score (cosine, RRF or reranker); null for expansion chunks
  rank                 null for expansion chunks
  added_because        "retrieved" | "amendment_of" | "amended_by" | "definition_for"
  linked_from          chunk_id that triggered the expansion, or null
```

Pydantic now rather than later: the frontend waits for "the response schema
is stable" (CLAUDE.md), and FastAPI (M5) reuses these models directly.

### 7. Pipeline and modes (`src/retrieval/pipeline.py`)

- `Retriever.retrieve(query, region, mode="hybrid_rerank", gate=True)`. The
  three modes are the configuration comparison in the evaluation plan
  (dense only vs hybrid vs hybrid + rerank) on identical code paths. The
  language gate and expansion are the same in all three modes, so the
  comparison isolates the retrieval method.
- Every mode has a gate score, so every mode can abstain:

  | Mode | Gate score |
  |---|---|
  | `dense` | top dense cosine similarity |
  | `hybrid` | top dense cosine similarity among the fused candidates (the RRF score is rank-based: the top value is nearly the same for every query and carries no relevance signal) |
  | `hybrid_rerank` | top reranker score |

  Thresholds are per mode (`retrieval.abstention_threshold.<mode>`).
  `gate=False` turns the gate off for evaluation runs (below).

### 7a. Comparing abstention fairly across modes (evaluation plan)

The plan first assumed the dense score separates in-scope from
out-of-scope questions poorly (devlog 2026-10-09: "nihao" 0.41, real
questions 0.66 to 0.69). The dev-list calibration did not support that: on
25 full-sentence questions dense AUC was 0.967, hybrid 0.973, reranker
0.960 (too few questions to tell them apart). So which gate is better is an
open question for the gold set, and the comparison must not favour any
mode, for example by gating one mode and not another, or by reusing one
mode's threshold for another. The rules:

1. **Same procedure for every mode.** Each mode's threshold is calibrated on
   its own gate score with the same gold items, the same folds (k-fold, see
   the note for Dr Azam) and the same selection rule. Selection rule: the
   highest threshold that keeps in-scope wrongly declined at or below a fixed
   budget (proposed 10%), chosen before the runs and the same for all modes.
   Abstention is then compared at equal cost to in-scope users.
2. **Report abstention as two numbers per mode**: % out-of-scope correctly
   declined and % in-scope wrongly declined, plus the threshold-free view
   (ROC AUC of the gate score, in-scope vs out-of-scope), which shows how
   well each score separates regardless of where the line is drawn.
3. **Answer quality separately, gate off.** RAGAS metrics for all three
   modes are computed on all in-scope items with `gate=False`, so every mode
   is scored on the identical item set. Otherwise a mode that declines more
   in-scope questions would be scored on fewer, easier items.
4. **End-to-end view, once, as a secondary table**: with each mode's
   calibrated gate on, the share of all items handled correctly (in-scope
   answered, out-of-scope declined).
5. Same generator, judge model and prompts across modes (CLAUDE.md).

`scripts/calibrate.py` therefore takes `--mode` and writes each item's gate
score per mode to file, so thresholds and ROC curves are computed from the
saved scores without rerunning retrieval.
- Embedder, store, BM25 and reranker are injected, so unit tests use fakes
  (same pattern as M2).
- Batch command `python -m src.retrieval.run questions.jsonl out.jsonl`:
  retrieval is deterministic, so its output can be saved once and handed to
  generation and evaluation on the HPC (M2 plan, decision 4).

### 8. Retrieval smoke checks

`python -m src.retrieval.smoke`, like the M2 smoke checks: sanity, not
evaluation.

| Query | Region | Expected |
|---|---|---|
| "maternity leave" | Sarawak | Cap. 76 s.84 chunk and A1754 s.24 both in the result |
| "how many days of maternity leave" | Sabah | Sabah s.2 "eligible period" in top 5 |
| "section 60E" | none | EA s.60E in the top 5 (rank 1 is EA s.100(4), the penalty for not granting leave "under section 60E": a fair hit, so "rank 1" was too strict) |
| "what does section 92 of the Employment Act say" | Peninsular | EA s.92 (short in-force section) |
| "what does section 30 of the Employment Act say" | Peninsular | EA s.30, a "(Deleted by Act A1026)." placeholder, found by BM25 although dense search excludes it |
| "cuti bersalin berapa hari" | Sabah | abstain, reason `language` |
| "Can I claim cuti sakit?" | Peninsular | not stopped by the language gate (reason is not `language`) |
| "can I bring my dog to work" | none | abstain, reason `low_score` |
| "how many days of maternity leave" | none | `multiple_jurisdictions` true |
| "how many days of maternity leave" | Peninsular | `multiple_jurisdictions` false |
| any Sabah or Sarawak query | Sabah / Sarawak | no EA chunk anywhere in the result |
| every smoke query | | at most 12 chunks |

## Config changes

```yaml
retrieval:
  reranker_model: BAAI/bge-reranker-large   # was null
  rerank_pool: 20
  top_k_final: 5
  max_chunks: 12                              # top 5 + at most 7 expansions
  exclude_placeholders_from_dense: true
  abstention_threshold:                       # moved from generation:
    dense: <provisional>
    hybrid: <provisional>
    hybrid_rerank: <provisional>              # decision 3
  reverse_amendment_cap: 3
  language_gate: {min_words: 3, min_english_share: 0.3}   # languages fixed in code
```

`generation.abstention_threshold` is removed: the threshold is on the
reranker score, so it belongs to retrieval.

## Tests (written first)

- Unit, no GPU or database: language gate (English passes, Malay and
  Chinese stop, short queries pass); placeholder filter in the SQL builder;
  mixed English and Malay passes; gate threshold edges (equal to threshold
  passes) and the right gate score per mode; `multiple_jurisdictions`
  (IRA alone does not set it); each expansion rule, the 12-chunk cap and its
  priority order, `expansions_dropped`, no duplicates, no self-links, `added_because` set; expansion never
  crosses jurisdiction; schema round trip; pipeline with fake components for
  each mode and each abstain reason; calibration sweep arithmetic on a toy
  score list.
- Integration, marker `db`: the smoke table above.

## Order of work

1. Experiment (decision 2), two parts:
   a. Reranker input, content vs citation + title + content, on
      section-number and natural queries.
   b. The 27 long chunks: count reranker tokens (query + chunk) per chunk,
      how many exceed 512, and how much text is cut. For each cut chunk,
      score a question aimed at the cut-off tail, first with the normal
      truncated input, then with a 512-token window that contains the tail.
      A large gap means the reranker is blind to the tail, and M3 uses a
      sliding window (chunk score = best window). Prepending the citation
      and title adds tokens, so part b runs with both inputs.
2. Schema and config.
3. Language gate (add `lingua-language-detector` to the image).
4. Placeholder filter, gate, expansion.
5. Pipeline, batch command, smoke checks.
6. Provisional threshold (decision 3), devlog, CLAUDE.md status.

## Decisions needing approval

1. **Language gate with `lingua`, short queries pass.** (Recommended.)
2. **Reranker input = citation + section title + content**, if task 1 shows
   it helps section-number queries without hurting natural ones. The CP1
   rule "only content is embedded" is about the embedding; the reranker is
   not an embedding. The dense side stays content only. (Recommended,
   subject to the experiment.)
3. **Threshold before the gold set exists.** Set a provisional threshold
   from a small dev list (about 15 in-scope, 10 out-of-scope questions),
   kept in `data/eval/dev_questions.jsonl`, separate from the gold set and
   never reported as a result. Replaced by the calibrated value once the gold
   set exists. (Recommended: M4 needs a working gate to develop against.)
   Alternative: leave the gate off until the gold set exists.
4. **Reverse amendment links capped at 3** in document order.
   (Recommended.) Alternative: no reverse links in M3.
5. **Region `None` searches all jurisdictions** and the result reports which
   jurisdictions it found. The UI decides later whether to ask the user for
   a region first. (Recommended.) Alternative: region required.

### For Dr Azam (evaluation method, not M3 code)

Calibrating the threshold on the same 60 to 80 gold items that the
abstention rates are reported on makes the rates look better than they are.
Suggest k-fold (for example 5-fold): choose the threshold on four folds,
report on the fifth, average. Keeps every item in the test set.
