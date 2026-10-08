"""Build the index: chunks.jsonl into PostgreSQL (dense) and BM25 (sparse).

    python -m src.indexing.build            # skips if nothing changed
    python -m src.indexing.build --force    # rebuild anyway

Steps: embed every chunk's content with bge-m3 (then release the GPU),
upsert the rows into PostgreSQL, delete rows from older builds, build and
save BM25, write a manifest.

The index version is a hash of chunks.jsonl. It is stored on every row and
in the manifest, so any retrieved chunk can be traced to the exact corpus
build that produced it. The frontend can keep it with saved chat history to
spot citations made against an older corpus.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src.indexing.bm25 import Bm25Index
from src.indexing.store import chunk_row


def index_version(chunks_path: str | Path) -> str:
    return hashlib.sha256(Path(chunks_path).read_bytes()).hexdigest()[:12]


def _load_chunks(chunks_path: Path) -> list[dict]:
    with chunks_path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def build_index(
    chunks_path: str | Path,
    embedder,
    store,
    bm25_dir: str | Path,
    manifest_path: str | Path,
    model: str,
    force: bool = False,
) -> dict:
    chunks_path, bm25_dir, manifest_path = Path(chunks_path), Path(bm25_dir), Path(manifest_path)
    version = index_version(chunks_path)
    chunks = _load_chunks(chunks_path)

    store.ensure_schema()
    if not force and manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            previous.get("index_version") == version
            and store.count(version) == len(chunks)
            and (bm25_dir / "chunks.json").exists()
        ):
            return {**previous, "skipped": True}

    started = time.perf_counter()
    try:
        dense, sparse = embedder.encode([c["content"] for c in chunks])  # content only (CP1 schema)
    finally:
        embedder.close()
    embed_seconds = round(time.perf_counter() - started, 1)

    store.upsert([chunk_row(c, d, s, version) for c, d, s in zip(chunks, dense, sparse)])
    removed = store.delete_other_versions(version)
    Bm25Index.build(chunks).save(bm25_dir)

    manifest = {
        "index_version": version,
        "chunks": len(chunks),
        "embedding_model": model,
        "embedding_dim": len(dense[0]) if dense else 0,
        "embed_seconds": embed_seconds,
        "removed_stale_rows": removed,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "skipped": False,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="rebuild even if nothing changed")
    parser.add_argument("--config", default="config/config.yaml")
    args = parser.parse_args()

    from src.indexing.embed import BgeM3Embedder
    from src.indexing.store import ChunkStore, connect

    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    settings = config["indexing"]
    chunks_path = Path(config["corpus"]["processed_dir"]) / "chunks.jsonl"
    with connect(config) as conn:
        manifest = build_index(
            chunks_path,
            BgeM3Embedder(settings["embedding_model"], settings["embed_batch_size"]),
            ChunkStore(conn, settings["embedding_dim"]),
            settings["bm25_dir"],
            settings["manifest_path"],
            model=settings["embedding_model"],
            force=args.force,
        )
    if manifest["skipped"]:
        print(f"index {manifest['index_version']} is up to date ({manifest['chunks']} chunks); nothing to do")
    else:
        print(
            f"built index {manifest['index_version']}: {manifest['chunks']} chunks, "
            f"{manifest['embedding_dim']}-dim, embedded in {manifest['embed_seconds']}s, "
            f"{manifest['removed_stale_rows']} stale rows removed"
        )


if __name__ == "__main__":
    main()
