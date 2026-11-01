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
meaning. The PDFs are committed, so a fresh clone has the full corpus and
the `corpus` tests run without extra setup.

## Setup

Python 3.12 specifically — 3.13/3.14 have no stable wheels yet for the
indexing stack.

Development runs on Linux (WSL 2) with Docker and an NVIDIA GPU. All Python
runs inside the `ml` container, so no local venv is needed:

```bash
cp .env.example .env                                        # then fill it in
docker compose up -d                                        # PostgreSQL + pgvector
docker compose --profile ml build ml                        # ML image, once
docker compose run --rm ml python -m pytest
```

## Ingestion

```bash
docker compose run --rm ml python -m src.ingestion.pipeline
```

Reads the five PDFs and writes to `data/processed/`:

- `chunks.jsonl`: one citation-ready chunk per line (schema in
  `docs/chunk_schema.md`)
- `toc_inventory.jsonl`: every section each ARRANGEMENT OF SECTIONS lists
- `ingestion_report.json`: counts, inferred titles, and validation problems

It exits with status 1 if any listed section has no chunk, or if editorial
text, missing citation fields or broken amendment links are found.

## Indexing

Set `POSTGRES_PASSWORD` in `.env` to any random string.

```bash
docker compose run --rm ml python -m src.indexing.build     # embed + index
docker compose run --rm ml python -m src.indexing.smoke     # sanity checks
```

The ML code (bge-m3, BM25) runs in the `ml` container. This started on
Windows, where Smart App Control blocked native DLLs in a venv; on Linux the
container is kept so local and HPC runs (Apptainer) share one environment.
`build` skips work when `chunks.jsonl` has not changed; `--force` rebuilds.

## Frontend

The web app lives in `frontend/` (Vite, React, TypeScript, Tailwind 4,
shadcn/ui). It runs on the host with Node 24, not in the `ml` container. Plan:
`docs/plans/2026-11-01-m6-frontend.md`.

```bash
# terminal 1: the API (GPU, see the M5 devlog for the generator cookie)
docker compose run --rm -p 127.0.0.1:8000:8000 ml uvicorn src.api.app:build --factory --host 0.0.0.0 --port 8000 --workers 1

# terminal 2: the app on http://localhost:5173 (Vite proxies /api to port 8000)
cd frontend
npm ci
npm run dev
```

Checks: `npm test -- --run`, `npm run typecheck`, `npm run lint`, `npm run build`.

## Recovery

Only the Docker volumes hold state: `<project>_getright-pgdata` (the index)
and `<project>_getright-hf-cache` (model weights), where `<project>` is
`COMPOSE_PROJECT_NAME` in `.env`. If the index is lost:

1. `data/processed/chunks.jsonl` is tracked in git. Check it still hashes to
   the index version you expect (`sha256`, first 12 hex digits).
2. `docker compose run --rm ml python -m src.indexing.build --force`
3. `docker compose run --rm ml python -m src.indexing.smoke`

Re-running ingestion is only needed when the PDFs or the parser change; it
produces a new index version, and gold chunk ids must then be rechecked.

`requirements.txt` installs only the milestone in progress; the indexing,
generation, and evaluation blocks are commented out and get pinned when that
work starts. Copy `.env.example` to `.env` for API keys — `.env` is gitignored.
