# Plan 2026-11-12: answer structure, limits callout, retrieval relevance, side-by-side sources

Author's request (2026-11-12), six items, done in this order. Branch `m6-frontend`.

## 1. Answer structure (prompt `m4-v3`)

- New rules: open with a direct answer in one or two sentences; then at most four short sections, each starting with a `## ` heading line; paragraphs or `- ` bullets; no bold, no tables.
- New rule: use only the sources that bear on the question asked; leave out sources about a different situation. Rule 1 (answer only from the sources, else `INSUFFICIENT_CONTEXT`) is kept word for word in meaning; the relevance rule narrows what is used, it never widens it.
- Every legal statement still carries a marker; citations still come only from block metadata (`citations.py` unchanged).
- Frontend renders `## ` headings, `- ` bullets and paragraphs with its own small line parser (React escapes text; no markdown library, no HTML). Replaces decision C5's "plain text".
- `PROMPT_VERSION` becomes `m4-v3`. All M4 numbers stay labelled `m4-v2`; answers made with v3 are not comparable without a re-run.

## 2. Limits callout (new field `limits`)

- The prompt asks for a final line `LIMITS: <one sentence>` saying what the sources cannot tell the user about their own situation, with no markers.
- `answer.py` takes that line out of the text before markers are resolved and returns it as `GeneratedAnswer.limits` (null when the model gives none, and always null for abstention / insufficient context). Markers on the line are removed.
- API returns it unchanged; OpenAPI and TypeScript types regenerated. Frontend shows it as a callout under the answer.

## 3. Retrieval relevance: findings and decision

Investigation (`scripts/explain_retrieval.py`, `exp_relevance.py`, `exp_contextual_dense.py`, `exp_reranker_model.py`), question "my boss fired me without any notice period", region peninsular, plus gold items RDT-005 to RDT-008:

- s.13(1) reaches the fused pool (rank 2, BM25 rank 1) but the reranker drops it to 12th (0.075); s.13(2) 9th (0.095). s.12(1)-(3) never enter the pool (not in dense or BM25 top 20; cosine 0.40-0.50); s.12(4) enters at pool rank 12, reranked 17th.
- The reranker puts s.14(1) (0.66) and s.81C (0.45) first: both literally say "dismiss ... without notice". s.12 / s.13 say "terminate ... contract of service" and "indemnity". The same pattern holds in all four gold dismissal items.
- Not fixed by: a score cut-off (any ratio), section-level scoring, a 40-candidate pool, embedding citation + title + content (hit@5 unchanged 0.926), the October query rewrite, or a newer reranker (bge-reranker-v2-m3, same top 5 pattern).
- Score cut-offs reduce noise but drop correct chunks: hit@5 0.926 -> 0.852 at ratio 0.1 (JPPM-008, JTKSM-05, JTKSM-35, SWK-008 lose every expected chunk; their correct chunks score 0.005-0.07 under a top of 0.3-0.99).

Decision taken here: no change to ranking; the relevance cut-off is implemented as `retrieval.context_min_ratio` (default null = off) so it can be switched on if the author and Dr Azam accept the recall cost. Relevance at the answer level is handled by the m4-v3 rule (use only sources that bear on the question). Options that could fix the cause, all needing Dr Azam: one-hop internal cross-reference expansion (hit@5 0.926 -> 0.944, context 5 -> 10.7 chunks, brings s.13(1) via s.21(1) but not s.12), a legal-domain reranker, or topic-aware query expansion.

## 4. Side-by-side source panel

- Wide screens (>= 1024 px): the panel is a column beside the answer (no overlay, no blur), the answer stays readable and scrollable. Narrow screens: the existing full-width Sheet.
- Clicking a citation highlights the sentence it belongs to in the answer (the sentence or bullet that ends with that marker).
- Previous / next buttons step through the citations in number order.
- Passage highlight inside the provision: the backend cannot supply it. Citations map a statement to a chunk, not to a span; a word-overlap guess would look like verification (core contribution 2). Not built; the panel shows the whole chunk as now.

## 5. Citation chips

- Visible number; `aria-label` and tooltip give the section reference ("Source 1: s. 14(1), Employment Act 1955").
- The model writes "... notice [1]." or "... notice. [1]"; the chip must sit after the punctuation with no gap: the renderer moves a full stop / comma that follows a marker group to before it, and removes the space before the marker.

## 6. Small fixes

- Source cards: no jurisdiction line (the question bubble shows the region).
- Bottom padding so the last source card clears the pinned question box.

## Kept

Visual style, dark mode, disclaimer, the panel note "GetRight does not check that it legally supports the statement", answer-only-from-sources and `INSUFFICIENT_CONTEXT`.
