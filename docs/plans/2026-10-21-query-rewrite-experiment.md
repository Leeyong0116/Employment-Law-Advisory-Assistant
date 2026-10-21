# Plan: offline query-rewrite experiment

Status: approved in chat 2026-10-21 (design below agreed with the author before writing).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure, offline, whether an LLM rewrite of the user's question before retrieval lowers in-scope wrong declines without giving up out-of-scope declines, under five gate rules tuned the same way.

**Architecture:** Each gold question (and the official Malay wording of 19 of them) is rewritten once by Qwen3 with the author's prompt and cached. Retrieval runs with the gate off on the original and on the rewrite, and both results are saved. Pure functions then tune and apply each gate rule with 5-fold cross-validation under the author's constraint (out-of-scope declined >= 70%). Out-of-scope questions that pass are answered and read by hand.

**Tech Stack:** Python 3.12, the M3 `Retriever`, the M4 `llm.py` / `Answerer`, LangChain `ChatPromptTemplate`, pytest. Runs in the ml container; needs the database and the HPC generator.

**Spec:** the design agreed in chat on 2026-10-21 (summarised in "Agreed design" below), CLAUDE.md (core contribution 3, scope discipline), `src/evaluation/retrieval_eval.py` (fold assignment and metrics to reuse).

## Agreed design (from the chat)

- Rewrite prompt, verbatim from the author:
  "Rewrite the user's question into formal Malaysian employment-law terms for searching statutes. Fix spelling. Translate Malay/Manglish words. Do NOT answer the question. Do NOT add facts, numbers, or legal conclusions that the user did not state. Output one sentence only."
- Language gate stays English-first. A Malay question is translated by the rewrite and answered in English (with a reminder to prefer English); other languages stay stopped. In this offline experiment that means: a Malay original that the language gate stops is scored with its rewrite.
- Do not trade out-of-scope declines for in-scope recall. Every rule is tuned with 5-fold CV so that out-of-scope declined >= 70% on the training folds; report the pooled held-out rates.
- Rules: baseline (original only), rewrite only, (a) max of original and rewrite, (b) original at its threshold OR rewrite at a stricter threshold, (c) rewrite used only when the original score is in a near-miss band below the threshold.
- Report in-scope wrong-decline rate overall, for the informal subset (the 5 in-scope Reddit items, RDT-*), and for the Malay variants (official `question_ms` from `data/eval/faq_candidates_all.csv`, 19 in-scope items).
- Every out-of-scope question that passes under any rule gets a generated answer, read by hand: does it cite wrong provisions, or correctly say the corpus does not cover it?
- Offline only. No change to `src/retrieval/`, `src/generation/`, `config/config.yaml` or `scripts/ask.py`.

## Global Constraints

- Gold v1 is not edited. Malay variants are new records with id `<gold id>-ms`, kept in the run files only.
- The rewrite never reaches the generator as the question: answers are generated for the original question, with the chunks of whichever retrieval the rule used.
- Same selection rule for every gate rule; external items (3, plus 1 Malay external) are excluded from tuning and reported apart.
- A score equal to a threshold passes (same as `src/retrieval/pipeline.py`).
- Fold assignment identical to `kfold_abstention` in `src/evaluation/retrieval_eval.py`: in-scope and out-of-scope ids each sorted and dealt round-robin into 5 folds. A Malay variant uses its English item's fold and that fold's tuned parameters.
- Rewrites at temperature 0, seed 0, thinking off, max_tokens 100; cached so every later stage is repeatable.
- Docs and devlog: plain English, no em dashes.

## Review Focus

1. A Malay original stopped by the language gate has no reranker score. Expected: scored as `STOPPED = -1.0` (declined at any threshold), never a crash or a silent pass. Test in Task 1.
2. The held-out out-of-scope rate can fall below 70% even when each training fold meets it (4 out-of-scope items per fold). Expected: the report shows the pooled held-out rate as measured, never the training rate. Test in Task 1.
3. A rule that cannot rescue anything without breaching the constraint (for example every out-of-scope rewrite scores high). Expected: tuning picks "never use the rewrite" (threshold infinity / empty band), so the rule falls back to baseline. Test in Task 1.
4. The model wraps its rewrite ("Rewritten question: ...", quotes, two lines). Expected: the cleaned rewrite is the sentence only. Test in Task 2.
5. The rewrite adds a number the user did not state (breaking the prompt). Expected: flagged per item (`added_numbers`) for the hand check, never silently used as if faithful. Test in Task 2.

---

### Task 1: Gate rules and 5-fold tuning (pure functions)

**Files:**
- Create: `src/evaluation/gate_rules.py`
- Test: `tests/unit/test_gate_rules.py`

**Interfaces:**
- Produces:
  - `STOPPED = -1.0`; `MIN_OOS_DECLINED = 0.70`
  - `Scored` (pydantic or dataclass): `id: str`, `in_scope: bool`, `orig: float`, `rew: float`, `fold_of: str` (the id whose fold it uses; its own id for gold items, the English id for `-ms` variants)
  - `select_oos_threshold(oos_scores: list[float], min_declined: float = MIN_OOS_DECLINED) -> float`: the lowest threshold that declines at least `ceil(min_declined * n)` of the scores (declined = score < threshold), i.e. `math.nextafter(sorted(oos)[k - 1], math.inf)`.
  - `passes(rule: str, item: Scored, params: dict) -> tuple[bool, str]`: whether the item is answered and which retrieval supplies the chunks (`"orig"` or `"rew"`). Rules and params:
    - `baseline` {t}: orig >= t, source orig
    - `rewrite` {t}: rew >= t, source rew
    - `max` {t}: max(orig, rew) >= t, source = the higher (orig on a tie)
    - `or_strict` {t_o, t_r}: orig >= t_o, source orig; else rew >= t_r, source rew
    - `band` {t, low}: orig >= t, source orig; else orig >= low and rew >= t, source rew
  - `tune(rule: str, train: list[Scored]) -> dict`: params chosen on training items only, using out-of-scope items for the constraint and maximising in-scope passes:
    - `baseline` / `rewrite` / `max`: `t = select_oos_threshold` on that rule's score.
    - `or_strict`: `t_o` as baseline; `t_r` = the lowest candidate >= `t_o` that keeps out-of-scope declined >= 70%, candidates `t_o`, `nextafter(rew)` of each out-of-scope item, and `math.inf`.
    - `band`: `t` as baseline; `low` = the lowest candidate that keeps the constraint, candidates every training `orig` below `t` and `t` itself (empty band).
  - `kfold(rule: str, items: list[Scored], k: int = 5) -> dict` with `out_of_scope_declined`, `in_scope_declined` (pooled over held-out folds, gold items only), `fold_params: list[dict]`, `decisions: dict[str, dict]` (per id, including `-ms` variants: `passed`, `source`, `fold`).

- [ ] **Step 1: Write the failing tests**

```python
def test_select_oos_threshold_declines_at_least_70_percent():
    oos = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    t = select_oos_threshold(oos)
    assert sum(s < t for s in oos) == 7 and t > 0.7 and t < 0.8

def test_score_equal_to_threshold_passes():          # passes("baseline", item(orig=0.5), {"t": 0.5})[0] is True
def test_stopped_original_is_declined_by_baseline():  # orig=STOPPED, rew=0.9 -> baseline False; rewrite True, source "rew"   (Review Focus 1)
def test_max_takes_source_of_higher_score():         # orig 0.2, rew 0.6 -> source "rew"; tie -> "orig"
def test_or_strict_falls_back_to_baseline_when_rewrite_cannot_help():   # every OOS rew = 0.99 -> t_r == math.inf   (Review Focus 3)
def test_band_empty_when_any_band_breaches_constraint():                  # -> low == t
def test_band_rescues_near_miss_in_scope_item():     # in-scope orig just under t with high rew, OOS orig far below -> passes, source "rew"
def test_kfold_uses_retrieval_eval_fold_assignment(): # same ids -> same folds as kfold_abstention's rule (sorted per scope, round-robin)
def test_kfold_reports_held_out_rate_not_training(): # construct folds where training meets 70% but held-out gives 50%; result == 0.5   (Review Focus 2)
def test_malay_variant_uses_parent_fold_and_is_excluded_from_rates():    # "JTKSM-05-ms" decided with JTKSM-05's fold params; not counted in in_scope_declined
```

- [ ] **Step 2: Run, expect FAIL** (`docker compose run --rm ml pytest tests/unit/test_gate_rules.py`: module not found)
- [ ] **Step 3: Implement `src/evaluation/gate_rules.py`** (module docstring: traceability, not legal correctness; same "score equal passes" rule as the pipeline)
- [ ] **Step 4: Run, expect PASS**
- [ ] **Step 5: Commit** `Add gate rules and 5-fold tuning for the rewrite experiment`

### Task 2: Rewrite prompt, cleaning and Malay variants

**Files:**
- Create: `src/evaluation/rewrite.py`
- Test: `tests/unit/test_rewrite.py`

**Interfaces:**
- Consumes: `build_chat_model`, `invoke_with_retry` from `src/generation/llm.py`.
- Produces:
  - `REWRITE_RULES: str` (the author's prompt, verbatim) and `REWRITE_PROMPT = ChatPromptTemplate.from_messages([("system", REWRITE_RULES), ("human", "{question}")])`
  - `clean_rewrite(text: str) -> str`: first non-empty line; strips a leading label (`Rewritten question:`, `Formal question:`, `Query:`, case-insensitive), surrounding quotes and whitespace; raises `ValueError` if nothing is left.
  - `added_numbers(original: str, rewrite: str) -> list[str]`: digit groups and number words (one to ninety-nine, hundred) in the rewrite that do not appear in the original.
  - `rewrite_query(chain, question: str, retries: int = 3) -> str`: `invoke_with_retry(chain, {"question": question}, retries)` then `clean_rewrite`.
  - `malay_variants(gold: list[dict], csv_path: Path) -> list[dict]`: for each gold id with a non-empty `question_ms` in the CSV, a copy of the gold item with `id = "<id>-ms"`, `question = question_ms`, `parent = <id>`; everything else (region, scope, expected_chunk_ids) unchanged.

- [ ] **Step 1: Write the failing tests**: `test_rules_are_the_authors_prompt_verbatim` (exact string), `test_clean_strips_label_quotes_and_extra_lines` (`'Rewritten question: "What are the employer\'s obligations ...?"\nNote: ...'` -> the sentence only; Review Focus 4), `test_clean_empty_raises`, `test_added_numbers_flags_new_numbers` (original "after 30 working days", rewrite "... within seven days ... after 30 days" -> `["seven"]`; Review Focus 5), `test_added_numbers_empty_when_faithful`, `test_rewrite_query_uses_the_question` (with `GenericFakeChatModel`: returns the cleaned reply; the rendered human message equals the question), `test_malay_variants_from_csv` (tmp CSV with two rows, one without `question_ms` -> one variant, id `JTKSM-05-ms`, same `expected_chunk_ids`, `parent == "JTKSM-05"`).
- [ ] **Step 2: Run, expect FAIL**
- [ ] **Step 3: Implement `src/evaluation/rewrite.py`**
- [ ] **Step 4: Run, expect PASS**
- [ ] **Step 5: Commit** `Add the query rewrite prompt and Malay variants for the experiment`

### Task 3: Experiment script, stages rewrite and score (live)

**Files:**
- Create: `scripts/exp_query_rewrite.py`

**Interfaces:**
- Consumes: Task 2 (`REWRITE_PROMPT`, `rewrite_query`, `added_numbers`, `malay_variants`), `Retriever.from_config`, `build_chat_model` with `max_tokens` overridden to 100.
- Produces (files under `data/eval/runs/`, prefix `2026-10-21_rewrite_`):
  - `rewrites.jsonl`: `{"id", "parent", "question", "rewrite", "added_numbers"}`, one per gold item and Malay variant (77 + 20 = 97), resumable (ids already present are skipped), flushed per line.
  - `records.jsonl`: `{"id", "variant": "orig" | "rew", "gate_score", "abstain_reason", "ranked", "final", "result"}` with `result` = the full `RetrievalResult` dump, retrieval mode `hybrid_rerank`, gate off. `gate_score` is `STOPPED` when the language gate stopped the query.

Command: `docker compose run --rm ml python scripts/exp_query_rewrite.py rewrite` then `... score`. Stages `report` and `answers` are added in Tasks 4 and 5.

- [ ] **Step 1: Run `rewrite`.** Expected: 97 lines; prints how many rewrites have `added_numbers`.
- [ ] **Step 2: Read 10 rewrites** (all 5 RDT, 5 Malay) and note in the ledger whether they look faithful.
- [ ] **Step 3: Run `score`.** Expected: 194 records; every `-ms` original has `abstain_reason == "language"` or a score; no English original is language-stopped.
- [ ] **Step 4: Commit** the script and the two run files: `Rewrite and score gold questions for the rewrite experiment`

### Task 4: Report stage

**Files:**
- Modify: `scripts/exp_query_rewrite.py` (stage `report`)

**Interfaces:**
- Consumes: Task 1 (`Scored`, `kfold`), the records file, `hit_at_k`, `reciprocal_rank`, `roc_auc` from `src/evaluation/`.
- Produces: `data/eval/runs/2026-10-21_rewrite_report.json` and a printed table with, per rule (`baseline`, `rewrite`, `max`, `or_strict`, `band`): out-of-scope declined (pooled held-out), in-scope wrongly declined (all 54; informal RDT in-scope, n = 5; Malay variants, n = 19), fold params, out-of-scope ids that pass. Also: ROC AUC of `orig`, `rew` and `max` scores; hit@5 and MRR on in-scope items with expected chunks for original vs rewrite, and for Malay variants (rewrite) vs their English originals.

- [ ] **Step 1: Run `report`.** Expected: `baseline` out-of-scope declined close to the earlier 5-fold figure (it uses a different selection rule, so not identical; note the difference).
- [ ] **Step 2: Commit** `Report the rewrite experiment`

### Task 5: Answers for passing out-of-scope questions, devlog

**Files:**
- Modify: `scripts/exp_query_rewrite.py` (stage `answers`)
- Create: `docs/devlog/2026-10-21_query-rewrite-experiment.md`
- Modify: `CLAUDE.md` (the pending two-signal gate bullet: add the rewrite result and the file names)

**Interfaces:**
- Consumes: the report's per-rule decisions, saved `result` dumps, `Answerer.from_config()`.
- Produces: `data/eval/runs/2026-10-21_rewrite_oos_answers.jsonl`: one line per (out-of-scope id, source) that passes under any rule: `{"id", "rules", "source", "answer": GeneratedAnswer}`. The `RetrievalResult` is given the original question (`model_copy(update={"query": original})`) before answering.

- [ ] **Step 1: Run `answers`.** Expected: one answer per passing (id, source).
- [ ] **Step 2: Read each answer** with its cited chunks; classify as "says not covered" (status `insufficient_context`, or text says the sources do not cover it) or "cites wrong provisions" (answers from provisions that do not cover the question), with one line why. Record in the devlog.
- [ ] **Step 3: Write the devlog** (results table per rule, subsets, AUC, hit@5/MRR, the out-of-scope answer reading, faithfulness of rewrites incl. `added_numbers`, limitations: 5 informal items, no Malay out-of-scope items, 20 out-of-scope items) and update CLAUDE.md. State the recommendation for Dr Azam.
- [ ] **Step 4: Commit** `Log the query rewrite experiment`

## Out of scope

Any change to the live pipeline, the language gate, the config or the dev console; a gold set v2; the two-signal (dense) gate itself (already measured, devlog 2026-10-10).
