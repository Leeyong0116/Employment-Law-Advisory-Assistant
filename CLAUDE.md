# Project Context

## What this is
A Retrieval-Augmented Generation (RAG) system that answers questions about
Malaysian labour law and cites the exact statutory provision behind every
answer (Act, Part, Section, page). Built as a Capstone Project (CP1 = design,
CP2 = implementation + evaluation).

## Statutory corpus (fixed scope — do not add other Acts without discussion)
- Employment Act 1955
- Industrial Relations Act 1967
- Labour Ordinance (Sabah, Cap. 67)
- Labour Ordinance (Sarawak, Cap. 76)

English text and English queries only for this phase (bge-m3 embeddings keep
Bahasa Malaysia extension possible later, but it is out of scope now).

## Architecture decisions already made (from the approved CP1 proposal)
- **Ingestion**: custom section parser, not a generic PDF-to-text dump. Must
  handle three hard cases: provisos attached to the subsection above them,
  omitted/placeholder sections, and the Employment Act's First Schedule
  (two-column table, not numbered sections). A validation script must confirm
  every section in the source appears in at least one chunk.
- **Indexing**: bge-m3 embeddings (dense) + sparse index, so both natural-
  language questions and direct section-number lookups work.
- **Retrieval**: hybrid dense + sparse, combined via a reranker.
- **Generation**: host api
- **Citation & abstention**: every claim in an answer must be traceable to a
  specific section. If nothing in the corpus supports an answer, the system
  abstains and states which statutes it holds, rather than guessing.
- **Interface**: kept as a separate service from the pipeline (not a
  Streamlit/Gradio single-process app), so the same pipeline API is used by
  the UI, the evaluation harness, and any automated tests.
- **Evaluation**: RAGAS — faithfulness, answer relevancy, context precision,
  context recall — against a self-built gold set of 60-80 Q&A items,
  stratified by topic, difficulty, and in-scope/out-of-scope.

## Explicitly out of scope for now
Case law / Industrial Court awards, Bahasa Malaysia queries, the other
Malaysian labour statutes (Minimum Wages Order, Children and Young Persons
Act, Workmen's Compensation Act, Minimum Retirement Age Act, Gig Workers Act
2025), agentic or graph-based retrieval, legal-correctness verification
(this project evaluates faithfulness, not legal correctness).

## Working conventions
- Python, one virtualenv, dependencies pinned in requirements.txt.
- Every module in src/ has a matching test in tests/.
- Don't touch data/raw/ contents directly in code — treat as read-only source
  documents; write derived output to data/processed/.
