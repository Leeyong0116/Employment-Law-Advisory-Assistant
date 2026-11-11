# Devlog 2026-11-12: answer structure, limits, retrieval relevance, side-by-side sources

Branch `m6-frontend`. Plan `docs/plans/2026-11-12-answer-structure-and-source-panel.md`. Author's request, six items, in order. Generator during this work: DeepSeek `deepseek-flash` (development only).

## 1. Summary

| Item | Result |
|---|---|
| 1 Answer structure | Prompt `m4-v3`: direct answer first, `## ` sections, bullets, only sources that bear on the question. Frontend renders headings and lists. Done. |
| 2 Limits callout | New field `GeneratedAnswer.limits` from the model's `LIMITS:` line; amber callout under the answer. Done. |
| 3 Retrieval relevance | Cause found (Section 4). Not fixed: no deterministic change tested retrieves s.12. Cut-off built but off (it costs recall). |
| 4 Side-by-side panel | Column beside the answer on screens >= 1024 px, sheet below; sentence highlight; previous / next. Passage highlight inside the provision not built (Section 5). |
| 5 Citation chips | Section reference on hover and for screen readers; chip after the punctuation, no gap. Done. |
| 6 Small fixes | Jurisdiction line removed from source cards; scroll column fixed and padded so Sources clear the question box. Done. |

Tests: backend 483 unit tests passed; frontend 46 passed. API smoke 7/7 (TestClient, new code). Type check, lint, build clean.

## 2. Prompt m4-v3 and the limits field

- Rules 1 and 3 to 8 are the m4-v2 rules. New rule 2: "Use only the sources that bear on the question asked. Leave out a source that is about a different situation." It narrows what is used; rule 1 (answer only from the sources, else `INSUFFICIENT_CONTEXT`) is unchanged.
- Format block: direct answer in one or two sentences; at most four `## ` sections (examples: "When it is allowed", "What must be paid", "What the worker can do next", the last described as what the law provides for, not advice); paragraphs or `- ` bullets; no bold or tables; a final `LIMITS: ` line without markers, said only there.
- `answer.split_limits` removes the line before markers are resolved; markers on it are dropped, not cited (it is not a statement of law). `limits` is null when the model gives no line and for abstention / insufficient context. OpenAPI and TypeScript types regenerated (staleness test caught the change).
- Real answers (DeepSeek, m4-v3): annual leave and Sarawak maternity follow the format; Sarawak still cites A1754 s.24 (98 days). Dismissal answer: s.81C (sexual harassment) left out in 2 of 3 runs, included once. DeepSeek still sometimes repeats the limit in the opening sentence and sometimes uses a marker as a noun ("source [2] sets ..."); the text is never edited after generation, so these are prompt-compliance issues.
- All M4 numbers stay `m4-v2` (Qwen3-14B). m4-v3 has not been run on the gold set.

## 3. Frontend

- `lib/answerText.ts`: line parser (headings, `- ` / `1. ` lists, paragraphs); each sentence is paired with the markers that close it; punctuation right after a marker group moves before it; `**` removed; unknown markers stay text. 5 unit tests.
- `AnswerView`: renders the blocks; `<mark>` on the sentence(s) of the selected citation; chips show the number, `title` and `aria-label` give "s. 14(1), Employment Act 1955" (`lib/citations.ts`, cut from the API label); limits callout (`role="note"`); source cards without the jurisdiction line, `aria-pressed` on the selected card.
- `SourcePanel`: `layout="side"` (an `aside` beside the answer, Escape closes, focus moves to the source heading) or `layout="sheet"` (narrow screens). Toolbar "Source n of m", previous, next, close. Provision view, status banners, amendment links and the traceability note unchanged.
- `App`: selection state, `useMediaQuery('(min-width: 1024px)')`, layout row (answer column + panel). Bug fixed: the scroll column lacked `min-h-0`, so in a flex column it grew past the screen and the end of the Sources list went under the question box; now it scrolls inside the page, with `pb-16`.
- A real m4-v3 answer (`answer_dismissal_m4v3.json`) is a test fixture: 2 headings, 5 bullets, limits callout, no "LIMITS" in the text, no space before a full stop.

## 4. Retrieval relevance: what was found

Question "my boss fired me without any notice period", region peninsular. Tools: `scripts/explain_retrieval.py` (stage-by-stage ranks), `scripts/exp_relevance.py`, `scripts/exp_contextual_dense.py`, `scripts/exp_reranker_model.py`. Records in `data/eval/runs/2026-11-11_exp_*` (container clock is UTC).

Before (current pipeline): context = s.14(1) 0.66, s.81C 0.45, s.81E(1) 0.30, s.21(2) 0.15, s.21(1) 0.14.

| Chunk | Dense rank | BM25 rank | Pool rank | Reranked | Reranker score |
|---|---|---|---|---|---|
| s.13(1) | 14 | 1 | 2 | 12 | 0.075 |
| s.13(2) | - | 2 | 11 | 9 | 0.095 |
| s.12(1) | - | - | - | - | 0.012 |
| s.12(2) | - | - | - | - | 0.063 |
| s.12(4) | - | 4 | 12 | 17 | 0.011 |

Cause: the cross-encoder ranks provisions whose text literally says "dismiss ... without notice" (s.14(1) misconduct, s.81C sexual harassment) far above the notice rules, which say "terminate ... contract of service" (s.12) and "indemnity" (s.13). s.12(1)-(3) also never reach the candidate pool (colloquial "fired", "boss", "notice period" vs statutory wording). Same pattern in all four gold dismissal items (RDT-005 to 008: 1, 0, 1, 2 expected chunks in the top 5).

What was tried (gold set v1, 54 in-scope items; baseline hit@5 0.926, recall@5 0.808, precision 0.233):

| Change | hit@5 | recall | precision | context size | Dismissal question |
|---|---|---|---|---|---|
| Score cut-off 0.1 x top | 0.852 | 0.719 | 0.382 | 3.5 | unchanged |
| Score cut-off 0.3 x top | 0.852 | 0.719 | 0.502 | 2.7 | s.14(1), s.81C, s.81E(1) |
| Section-level scoring, pool 40 | 0.852 | 0.748 | 0.207 | 5 | s.14(1)-(3), s.81C, TLB reg. 4(1) |
| Top 10 | 0.944 | 0.849 | 0.128 | 10 | adds s.13(2) at rank 9 |
| One-hop internal cross-references | 0.944 | 0.842 | 0.160 | 10.7 | adds s.13(1) (via s.21(1)), no s.12 |
| Dense on citation + title + content | 0.926 | 0.808 | - | 5 | unchanged |
| bge-reranker-v2-m3 instead of -large | 0.926 (MRR 0.810) | 0.796 | - | 5 | s.14(1), s.81C, s.21(2), s.21(1), s.57 |
| Query rewrite (2026-10-21 run) | - | - | - | 5 | RDT items no better |

Score cut-offs lose every expected chunk for JPPM-008, JTKSM-05, JTKSM-35 and SWK-008: their correct chunks score 0.005 to 0.07 under top scores of 0.12 to 0.99. So a reranker-score cut-off trades recall for precision; at the answer level, prompt rule 2 does the filtering instead.

Decision: ranking unchanged; `retrieval.context_min_ratio` added (null = off, 3 unit tests), applied after the gate (never changes answer / abstain) and only in `hybrid_rerank`. Gate figures unchanged.

After (this change): retrieval output for the dismissal question is unchanged; the answer no longer restates unrelated provisions in most runs (prompt rule 2), and its limits are shown apart. s.12 / s.13 are still missing, so the answer still cannot state the notice periods.

Options that need Dr Azam: one-hop cross-reference expansion (small recall gain, double the context), a legal-domain reranker or fine-tuned cross-encoder, topic-aware query expansion, or a gold-set v2 check of any of these.

## 5. Not done, or unsure

- Passage highlight inside the provision: not built. A citation maps a statement to a chunk, not to a span; a word-overlap guess would look like verification (core contribution 2).
- Visual check in a real browser: not possible here (no browser). Covered by component tests in jsdom only; the author checks the screen.
- The running API must be restarted to load prompt m4-v3 and the `limits` field.
- m4-v3 with Qwen3-14B and on the gold set: not run.
