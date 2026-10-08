"""Try the index by hand: dense (bge-m3) and BM25 results side by side.

    docker compose run --rm ml python scripts/search.py
        interactive: loads the model once, then asks for questions

    docker compose run --rm ml python scripts/search.py "annual leave" --region sabah
        one question, then exit

In interactive mode, start a line with a region to filter:
    sabah: how many days of maternity leave
    peninsular: overtime on a public holiday
Type "quit" to stop.

This is a playground for learning how retrieval behaves. It is not the
retrieval pipeline (that is M3: combining both lists, reranking, following
amendment links).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.indexing.bm25 import Bm25Index  # noqa: E402
from src.indexing.embed import BgeM3Embedder  # noqa: E402
from src.indexing.store import ChunkStore, connect  # noqa: E402

REGIONS = ("peninsular", "sabah", "sarawak")


def _show(title: str, hits: list[tuple[str, float]], chunks: dict, width: int) -> None:
    print(f"\n  {title}")
    if not hits:
        print("    (nothing found: no query word appears in any chunk)")
    for rank, (chunk_id, score) in enumerate(hits, start=1):
        chunk = chunks[chunk_id]
        flags = []
        if chunk["status"] != "in_force":
            flags.append(chunk["status"].upper())
        if chunk.get("amended_by"):
            flags.append("amended by " + ", ".join(chunk["amended_by"][:2]))
        flag = f"  [{'; '.join(flags)}]" if flags else ""
        print(f"    {rank}. {score:6.3f}  {chunk['citation']}{flag}")
        snippet = " ".join(chunk["content"].split())
        print(f"              {snippet[:width]}{'...' if len(snippet) > width else ''}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Search the index by hand.")
    parser.add_argument("query", nargs="?", help="question; omit for interactive mode")
    parser.add_argument("--region", choices=REGIONS, help="only chunks that apply in this region")
    parser.add_argument("--k", type=int, default=5, help="results per method (default 5)")
    parser.add_argument("--width", type=int, default=110, help="snippet length")
    args = parser.parse_args()

    config = yaml.safe_load(Path("config/config.yaml").read_text(encoding="utf-8"))
    settings = config["indexing"]
    manifest = json.loads(Path(settings["manifest_path"]).read_text(encoding="utf-8"))
    chunks_path = Path(config["corpus"]["processed_dir"]) / "chunks.jsonl"
    chunks = {c["chunk_id"]: c for c in map(json.loads, chunks_path.open(encoding="utf-8"))}

    print("loading bge-m3 (about 20 seconds the first time)...")
    embedder = BgeM3Embedder(settings["embedding_model"], settings["embed_batch_size"])
    embedder.encode(["warm up"])
    bm25 = Bm25Index.load(settings["bm25_dir"])

    with connect(config) as conn:
        store = ChunkStore(conn, settings["embedding_dim"])

        def ask(query: str, region: str | None) -> None:
            allowed = config["retrieval"]["regions"][region] if region else None
            vector = embedder.encode([query])[0][0]
            print(f"\nQ: {query}   [{region or 'all regions'}]")
            _show("DENSE (bge-m3, meaning)", store.dense_search(vector, args.k, allowed, manifest["index_version"]),
                  chunks, args.width)
            _show("BM25 (keywords)", bm25.search(query, args.k, allowed), chunks, args.width)

        if args.query:
            ask(args.query, args.region)
            return

        print('\nType a question, e.g. "sabah: how many days of maternity leave". "quit" to stop.')
        while True:
            try:
                line = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                continue
            if line.lower() in ("quit", "exit", "q"):
                break
            region = args.region
            head, _, rest = line.partition(":")
            if head.strip().lower() in REGIONS and rest.strip():
                region, line = head.strip().lower(), rest.strip()
            ask(line, region)
    embedder.close()


if __name__ == "__main__":
    main()
