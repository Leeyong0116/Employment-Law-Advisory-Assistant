"""M5: GetRight over HTTP (FastAPI over the Retriever and the Answerer).

Run the server (database up first: docker compose up -d):

    docker compose run --rm -p 127.0.0.1:8000:8000 ml uvicorn src.api.app:build --factory --host 0.0.0.0 --port 8000 --workers 1

0.0.0.0 is inside the container; the port mapping keeps it on localhost.
One worker: bge-m3 and the reranker are loaded once and share one GPU.

Smoke check (needs a fresh OOD cookie in .env): python -m src.api.smoke
"""
