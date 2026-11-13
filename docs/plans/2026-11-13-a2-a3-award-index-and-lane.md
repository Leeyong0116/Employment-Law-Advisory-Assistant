# Plan A2 + A3 (2026-11-13): award index and award retrieval lane

Design: `docs/superpowers/specs/2026-11-13-industrial-court-awards-design.md`, Sections 5 and 6 (decision A-D2: separate lane, statutes ranked and gated exactly as now, at most 2 award paragraphs, awards never push out a statute and never open the gate). Input: `data/processed/award_chunks.jsonl` from A1 (19 awards, 1,143 chunks, author's audit 38/38).

Status: **draft, waiting for the author's approval.**

## Goal

- **A2:** award chunks in the same PostgreSQL table as the statutes, a new index version, statute rows and vectors unchanged.
- **A3:** after the statute gate passes, a second ranking over awards only adds at most 2 award paragraphs that score at or above an award threshold, with the region rule.
- **Hard check for both:** gold v1 retrieval results (`python -m src.evaluation.retrieval_eval`) identical per item, not only in the averages.

## Boundaries

- No prompt, `Citation`, API schema or frontend change (A4, A5). No gold set change, no recalibration (A6).
- The award lane ships **switched off** in `config.yaml` at the end of A3 (`award_lane.enabled: false`). Prompt m4-v3 would show an award block with a statute-style header and no "one case" rule, so the API must not see awards until A4 adds prompt m4-v4. Tests and the A3 checks switch it on explicitly.
- `chunks.jsonl` and the A1 parser are not touched.

## Decisions in this plan (please confirm or change)

| # | Decision | Why |
|---|---|---|
| P1 | **Separate BM25 index for awards** (same tokenizer, same class, same settings, its own files in `data/processed/index/bm25_awards/`). The statute BM25 is rebuilt from the same statute chunks, so it stays identical. | BM25 scores depend on corpus-wide statistics (IDF, average length). Measured today: one BM25 over statutes + awards changes the statute top-20 list for **76 of 77** gold v1 questions (top 5 for 52), even after removing award hits. One shared BM25 cannot meet "gold v1 must not move". The design's "same BM25" is kept in the sense of same method. |
| P2 | **Statute vectors reused, not re-embedded.** The build reads the stored vector of each statute chunk and reuses it when chunk_id, content and embedding model are unchanged; only new or changed chunks are embedded. `--reembed` forces a fresh embedding of everything. | Makes "statute vectors unchanged" true by construction. Re-embedding should give the same numbers, but bge-m3 sorts each input list by length into batches, so mixing awards into the call changes batch shapes, and fp16 GPU results can then differ in the last digits. Reuse removes the doubt and costs about 15 lines. |
| P3 | **New `doc_type` column** in the `chunks` table: `award` for award chunks, `statute` for everything else (statute chunks have no `doc_type` field today; the registry's `principal` / `subsidiary` stays in the registry). Added with `ALTER TABLE ... ADD COLUMN IF NOT EXISTS ... DEFAULT 'statute'`. `dense_search` gets `doc_type="statute"` as its **default**, so every existing caller (pipeline, smoke, `scripts/search.py`, `scripts/compare.py`) stays statute-only without edits. | Awards have jurisdiction "Malaysia", the same as the IRA, so the jurisdiction filter alone would let them into the statute lane for every region. |
| P4 | **Index version = hash of `chunks.jsonl` + `award_chunks.jsonl`.** The version changes once now, so every statute row gets the new version stamp (metadata only; vectors reused per P2). Manifest records both counts. | One version still traces any chunk to one corpus build, as now. |
| P5 | The lane runs **only in `hybrid_rerank` mode** (the API's fixed mode). `dense` and `hybrid` modes stay statute-only. | Those modes exist for the statute configuration comparison; the award threshold is a reranker score. |
| P6 | The lane runs when the statute result is **not abstained**. With the gate on that means the gate passed; with the gate off (evaluation runs) it runs for every question that has candidates. | Same rule in both cases; the gate decision itself never looks at awards. |
| P7 | Award chunks come **after** the statute chunks and their expansion, outside the `max_chunks` cap (12), so a result holds at most 12 + 2 = 14 chunks. They get `added_because: "award"`, `score` = award reranker score, `rank` = null. | "Awards never push out a statute": they cannot take an expansion slot either. `rank` stays the statute lane's rank, so code that looks for `rank == 1` (`scripts/calibrate.py`) keeps meaning the top statute. |
| P8 | **Region rule** from data, not a hand list: a statute's territory is the jurisdiction of its chunks in `chunks.jsonl` (EA -> Peninsular Malaysia and Labuan, IRA -> Malaysia, Labour Ordinance (Sabah) -> Sabah, ...). An award is allowed for a region when every name in its `statutes_applied` has a jurisdiction in that region's list. No region given: all awards allowed (all statutes are searched then too). A `statutes_applied` name that matches no statute is an error at start-up, not a silent pass. | Core contribution 4. Today: 2 awards apply the EA (1821, 1942; 180 chunks) and are excluded for Sabah and Sarawak; the other 17 apply only the IRA and are allowed everywhere, including the Sabah (1900) and Sarawak (1891) awards. |
| P9 | `jurisdictions_found` and `multiple_jurisdictions` are computed from **statute chunks only**. | An award ("Malaysia") must not add the IRA jurisdiction note to the prompt or change the multi-territory flag. |
| P10 | Award lane settings in config: `top_k_dense: 20`, `top_k_sparse: 20`, `rerank_pool: 10`, `max_awards: 2`, `threshold: <provisional>`. | Pool 10, not 20: award paragraphs are long (sliding windows), and the lane adds a second reranker pass to every answered question. Latency is measured in Task 9. |

## A2: index (TDD)

**Task 1. `bm25.py`: filter by document.** `Bm25Index` keeps `doc_ids` beside `jurisdictions` (saved in `chunks.json`); `search(..., doc_ids=None)` limits hits to those documents. Tests: the filter works; a statute-only build gives the same scores and order with or without the new field.

**Task 2. `store.py`: `doc_type` column and filter.**
- `chunk_row` sets `doc_type` (`award` / `statute`).
- `ensure_schema` adds the column and an index if missing (existing table keeps its rows).
- `dense_search(..., doc_type="statute", doc_ids=None)`.
- New `stored_vectors(chunk_ids)`: chunk_id -> (content, dense vector, sparse weights), for P2.
- Tests (db marker, as the existing store tests): award rows never returned by a default search; `doc_type="award"` returns only awards; `doc_ids` filter in SQL; an old table without the column gets it.

**Task 3. `build.py`: two inputs, reuse, two BM25 indexes.**
- `index_version(chunks_path, award_path)`: changes when either file changes.
- `build_index(..., award_chunks_path=None, award_bm25_dir=None, reembed=False)`: statutes and awards embedded in separate calls (statutes first, as before); stored vectors reused per P2; statute BM25 to `bm25_dir` from statute chunks only; award BM25 to `award_bm25_dir`; manifest gains `award_chunks`, `reused_vectors`, `embedded`.
- Skip check counts both files.
- Config: `indexing.award_bm25_dir: data/processed/index/bm25_awards`.
- Tests (fake embedder and store, as now): awards embedded in their own call; unchanged statute chunks not re-embedded; a statute chunk whose content changed is re-embedded; `--reembed` embeds all; the statute BM25 built with awards present equals one built from statutes alone; old behaviour when no award file is given.

**Task 4. Index smoke.** `src.indexing.smoke` stays 7/7 (statute checks, default statute filter) plus 2 award checks: an award-only dense search and an award BM25 search for a dismissal query each return an award chunk; and a check that the statute search never returns one.

**Task 5. Build and verify.**
1. Before any code change: `retrieval_eval` on the current index (`459843bf28ba`) as the baseline, saved with a label (Task 8 adds `--label`; until then the dated files are copied by name).
2. `docker compose run --rm ml python -m src.indexing.build` -> expect 1,897 reused, 1,143 embedded, 3,040 rows, new version.
3. Index smoke 9/9.
4. `retrieval_eval` again; a small compare script (`scripts/compare_retrieval_runs.py`) checks every (mode, item) record: `ranked`, `final` and `gate_score` equal. Expect 0 differences in all three modes.

## A3: award lane (TDD)

**Task 6. `schema.py`.**
- `RetrievedChunk` gains `doc_type: Literal["statute", "award"] = "statute"` and optional award fields copied by `from_chunk`: `case_name`, `award_number`, `award_date`, `paragraph`, `venue`, `chairman`, `statutes_applied`, `source_page_end`.
- `AddedBecause` gains `"award"`.
- `RetrievalResult` gains `award_threshold: float | None` (null when the lane is off).
- `GeneratedAnswer` does not include `RetrievedChunk`, so the OpenAPI file and frontend types do not change in A3 (`test_openapi_dump` will confirm).
- Tests: `from_chunk` on a real award chunk (section None, doc_type award, fields kept); a statute chunk still gives `doc_type="statute"`.

**Task 7. `pipeline.py`: the lane.**
- `from_config` loads award chunks (appended after statute chunks in `self.chunks`, statute order unchanged) and the award BM25.
- The `Expander` gets statute chunks only.
- The query vector is computed once and shared by both lanes (a refactor of `_rank` that must not change statute results; covered by the existing tests).
- `_award_lane(query, vector, region)`: allowed award documents for the region (P8) -> dense (`doc_type="award"`, `doc_ids`) + award BM25 (`doc_ids`) -> RRF -> top `rerank_pool` -> reranker -> keep scores >= threshold -> first `max_awards`.
- Tests with fakes:
  - statute lane called with the statute filter;
  - an award with a higher score than every statute never enters the statute top k;
  - gate fails -> abstained, award lane not called;
  - at most 2 awards added, after expansion, `added_because="award"`, `rank` null;
  - below-threshold awards dropped, so zero awards is a normal result;
  - an award applying the EA is excluded for sabah and sarawak and allowed for peninsular and for no region; an IRA-only award is allowed everywhere;
  - unknown `statutes_applied` name -> error at start-up;
  - lane disabled, or mode dense / hybrid -> no awards and a result equal to today's;
  - lane on vs off -> identical statute chunks, scores and gate score;
  - `jurisdictions_found` ignores awards.

**Task 8. Callers that assume statute-only results.**
- `retrieval_eval.run()`: `ranked` and `final` keep statute chunks only; new `awards` list per record (chunk id and score), so statute metrics cannot move by construction and the award output is still saved. `--label` names the output files.
- `src/retrieval/smoke.py`: the chunk cap check allows `max_chunks + max_awards`.
- `scripts/calibrate.py`: picks the top statute explicitly.
- Checks with tests, no code change expected:
  - `Expander` with an award id present does nothing for it;
  - `Engine.provision("ICA2025_1806_p17")` returns a `Provision` with `section` null and `section_chunk_ids` = [the chunk itself];
  - `GET /api/provisions/{award id}` is 200.
- Known gap, left for A4: `Provision` has no `case_name`, `award_number`, `award_date`, `chairman`, `venue`, `paragraph`, so the source panel cannot show the award header yet.

**Task 9. Provisional award threshold and checks.**
- `scripts/award_lane_probe.py` runs the gold v1 questions with the lane on and no threshold. It prints, per question, the top 2 award citations and scores, grouped by topic, and the share of questions that would get at least one award at candidate thresholds.
- I pick a provisional value that lets awards through on dismissal and termination questions and mostly not on leave or hours questions, then show you a sample of the paragraphs it would add, to read for relevance.
- Recorded in config as **PROVISIONAL, never report** (like the M3 dev thresholds); calibrated on gold v2 in A6.
- Gold v1 is used here only to look at score ranges, not to tune a reported number.
- Then:
  - `retrieval_eval --label a3-lane-on` with the lane switched on: statute records identical to the baseline (compare script, 0 differences); award counts per topic and region in the report;
  - retrieval smoke 12/12;
  - latency of one question with the lane on vs off;
  - no award leaks across regions on the gold questions (an EA-applying award never shown for sabah / sarawak);
  - full `pytest` (backend count today: 511).
- At the end, the lane is set back to `enabled: false` (Boundaries).

## Docs

- README: "Index" section (two BM25 indexes, reuse, `--reembed`).
- `config.yaml` comments.
- CLAUDE.md status.
- Devlog for the session.
- Report to Dr Azam with the existing award items: P1 (separate BM25) and that gold v1 was unchanged per item.

## Risks

- **Award paragraphs that only restate facts or evidence** scoring high on wording. A1 kept reasoning ranges only, but the probe in Task 9 is where this shows; the threshold and the author's reading are the guard.
- **Reranker time.** A second pass on long paragraphs; if Task 9 shows it is too slow, cut `rerank_pool` before anything else.
- **The two EA-applying awards** are the only ones the region rule removes, so the rule has a thin test on real data. The unit tests carry it, including the Sabah / Sarawak Labour Ordinance cases that no current award has.
