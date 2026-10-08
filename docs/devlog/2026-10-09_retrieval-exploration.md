# Development log: retrieval exploration tools and first M3 components (9 October 2026)

Source material for the CP2 report. Follows `2026-10-08_m2-indexing.md`.

---

## 1. Summary

With the index built, the session was spent understanding how the three
retrieval methods behave on this corpus before designing M3. Two hand tools
were built, the first two M3 components were implemented and tested, and
the observations below were recorded. 218 tests pass.

## 2. What was built
*Report: Implementation (retrieval).*

| File | What it is | Status |
|---|---|---|
| `src/retrieval/fusion.py` | Reciprocal rank fusion (RRF, c = 60) of ranked lists | M3 component, tested |
| `src/retrieval/rerank.py` | bge-reranker-large cross-encoder over a candidate list | M3 component, tested |
| `scripts/search.py` | Terminal tool: dense and BM25 results side by side, interactive, region filter | Learning tool |
| `scripts/compare.py` | Local web page: Dense, BM25, Hybrid (RRF), Hybrid + Rerank in four columns, with rank movement, status flags and timings | Learning and inspection tool |

Run the comparison page:
```
docker compose up -d
docker compose run --rm -p 127.0.0.1:8000:8000 ml python scripts/compare.py
```
then open http://localhost:8000. It is not the M3 pipeline: no abstention
gate, no amendment-link following, no definition co-retrieval.

**Design notes:**
- RRF uses ranks only, because dense similarity (0 to 1) and BM25 (no upper
  bound) are on different scales. c = 60 follows Cormack, Clarke and
  Buettcher (2009). Ties broken by `chunk_id`, as everywhere else.
- Reranker: `BAAI/bge-reranker-large` (open source, same BGE family as
  bge-m3, runs locally so questions never leave the machine). Its
  successor `bge-reranker-v2-m3` is more multilingual; relevant only if
  Bahasa Malaysia is added later (out of scope now).
- Pipeline shape (retrieve-then-rerank): BM25 top 20 and dense top 20, fused
  by RRF, top 20 reranked, top 5 kept. Reranking all 1,852 chunks per query
  would take about a minute; 20 take about 0.6 s on the RTX 3070 Ti.

## 3. Worked numbers (useful as report figures)
*Report: Background / Method (how each retriever scores).*

All computed on the real index (1,852 chunks, average 49.7 tokens).

**BM25, query "maternity leave", Sabah** (bm25s defaults k1 = 1.5, b = 0.75):

| | IDF |
|---|---|
| "maternity" (in 75 chunks) | 3.20 |
| "leave" (in 117 chunks) | 2.76 |

| Chunk | Length | "maternity" | "leave" | Total |
|---|---|---|---|---|
| s.2(1) definition of "eligible period" (the 98-day answer) | 22 | tf 1 → 4.27 | tf 1 → 3.68 | 7.95 |
| s.104D(3) (annual leave) | 49 | tf 3 → 5.35 | tf 10 → 6.00 | **11.36** |

BM25 ranks the annual-leave provision first because "leave" occurs ten
times; term-frequency saturation limits but does not remove that pull.

**Dense (bge-m3), cosine similarity:**

| Pair | Cosine |
|---|---|
| "my boss fired me" / "the employer terminated the contract of service" | 0.737 (no word in common) |
| "maternity leave" / "annual leave" | 0.728 (different entitlements, nearly as close) |
| "my boss fired me" / "maternity leave" | 0.501 |
| "nihao" / "maternity leave" | 0.353 (unrelated, still well above 0) |

**Reranker (bge-reranker-large, normalised), same Sabah candidates:**

| Candidate | Score |
|---|---|
| s.2(1) "eligible period" (98 days) | 0.905 |
| s.83(4) | 0.866 |
| s.83(3) | 0.814 |
| s.87(2) | 0.514 |
| s.104D(3) (annual leave, BM25's top hit) | 0.024 |
| any candidate for "nihao" or "can I bring my dog to work" | 0.000 |

**Hybrid:** on the same query, RRF moves the 98-day definition to rank 1
(dense 1, BM25 4: 1/61 + 1/64) above the annual-leave provision (BM25 1
only: 1/61).

## 4. Observations that shape M3
*Report: Design (retrieval), Limitations.*

1. **Every method always returns something.** Dense gave "nihao" a top
   score of 0.41 (normal questions: 0.66 to 0.69). Only the reranker
   separates cleanly (0.000). The abstention gate must therefore use the
   reranker score, with the threshold calibrated on in-scope versus
   out-of-scope gold questions, not chosen by hand.
2. **Placeholder chunks attract nonsense queries.** For "nihao" the dense
   top 5 were all "(Omitted)." chunks: near-empty content gives a vector
   that is a little similar to everything. M3 option: leave deleted and
   omitted placeholders out of dense retrieval unless the query names that
   section (they stay reachable by section-number lookup).
3. **Language gate is needed** (CLAUDE.md): a non-English query should be
   stopped before retrieval, not answered from the nearest junk.
4. **The reranker does not know legal status.** It scores superseded
   Sarawak Cap. 76 s.84(1) (60 days) highly for a maternity question,
   because the text does answer it. Following `amended_by` links and using
   `status` must happen outside the model (see M2 devlog, Section 5).
5. **Wording gaps remain hard.** "can my employer cut my salary" did not
   bring EA s.24 (lawful deductions) into the top 3 for dense or BM25: the
   statute says "deductions from wages". A good gold-set question.
6. **The methods are complementary in practice:** BM25 wins on "section
   60E" and exact terms; dense wins on "my boss fired me without telling
   me"; the reranker corrects both on near-miss topics (annual versus
   maternity leave). This is the qualitative case for hybrid + rerank; the
   quantitative case is the planned RAGAS comparison (dense only vs hybrid
   vs hybrid + rerank).

## 5. Tests

218 passing (8 new): RRF formula, rank-not-score fusion, tie-breaking,
empty input; reranker ordering and tie-breaking with a fake cross-encoder.

## 6. Next steps

1. M3 plan: abstention threshold calibration, language gate, amendment-link
   and definition co-retrieval, placeholder handling (observation 2).
2. Gold set: collect external questions; include near-miss cases such as
   salary deduction and out-of-scope questions (EPF, SOCSO).
3. Ask Dr Azam about Sunway HPC use for M4.
