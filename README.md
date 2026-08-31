# Malaysian Labour Law RAG — CP2 Implementation

Starter scaffold matching the architecture and work plan from the CP1
proposal. See `CLAUDE.md` for the project context Claude Code / Superpowers
will read automatically.

## Layout

```
config/             # config.yaml — model names, index paths, thresholds
data/
  raw/               # source PDFs (the 4 Acts) — read-only
  processed/         # parsed sections / chunks (output of src/ingestion)
  eval/              # the 60-80 item gold Q&A set
src/
  ingestion/         # PDF parsing, section parser, validation script
  indexing/          # bge-m3 embeddings, sparse index, metadata store
  retrieval/         # dense + sparse retrieval, reranker, hybrid combine
  generation/         # LLM call, citation assembly, abstention logic
  evaluation/        # RAGAS harness (faithfulness, relevancy, precision, recall)
  api/               # backend service exposing the pipeline (used by frontend,
                      # evaluation, and tests alike)
frontend/            # the interface, built against the API's response schema
tests/
  unit/
  integration/
notebooks/           # exploration / prototyping, not production code
scripts/             # one-off utilities (e.g. corpus validation)
docs/                # reference copies of the proposal, rubric, etc.
```

This mirrors the CP2 Gantt order: ingestion → indexing → (retrieval +
gold-set construction in parallel) → generation → abstention calibration →
evaluation → frontend.

## Getting started with Superpowers

Superpowers works inside a Claude Code session (terminal or IDE), not in
this chat. From this folder:

```bash
cd malaysian-labour-rag
git init
claude
```

Then, instead of asking it to write code straight away, describe the first
slice of work and let the `brainstorming` skill drive it, e.g.:

> "I want to build the section parser described in CLAUDE.md — it needs to
> handle provisos, omitted sections, and the First Schedule table. Let's
> brainstorm the approach before writing anything."

Superpowers will walk brainstorm → spec → plan → (worktree) → TDD for that
one component, rather than for the whole project at once. Do this one
CP2 milestone at a time (ingestion first, since indexing and retrieval
depend on its output).

## Corpus

Five PDFs in `data/raw/` cover the four statutes — Sarawak needs two, because
the principal Ordinance and its 2025 amending Act are held as separate
documents rather than merged into a consolidated text. `config/config.yaml`
declares the registry (jurisdiction, currency date, in-force status, amendment
links); the filenames themselves are inconsistent and are never parsed for
meaning. The PDFs are gitignored, so a fresh clone needs them supplied
separately.

## Setup

Python 3.12 specifically — 3.13/3.14 have no stable wheels yet for the
indexing stack.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pytest
```

`requirements.txt` installs only the milestone in progress; the indexing,
generation, and evaluation blocks are commented out and get pinned when that
work starts. Copy `.env.example` to `.env` for API keys — `.env` is gitignored.
