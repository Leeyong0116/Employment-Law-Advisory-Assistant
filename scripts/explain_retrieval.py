"""Explain one retrieval: where chosen chunks sit at every stage (diagnostic, read only).

    docker compose run --rm ml python scripts/explain_retrieval.py "my boss fired me without any notice period" \
        --region peninsular --watch EA1955_s12_1 EA1955_s12_2 EA1955_s13_1 EA1955_s13_2

Prints the dense top k, the BM25 top k, the RRF pool, the reranker scores of the pool,
and for each watched chunk its rank at every stage plus its reranker score even when it
never reached the pool. Uses the same components and config as src/retrieval/pipeline.py.
"""

from __future__ import annotations

import argparse

from src.retrieval.fusion import rrf
from src.retrieval.pipeline import PLACEHOLDER_RULES, Retriever


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--region", default=None)
    parser.add_argument("--watch", nargs="*", default=[])
    parser.add_argument("--show", type=int, default=12)
    args = parser.parse_args()

    r = Retriever.from_config()
    s = r.settings
    allowed = s["regions"][args.region] if args.region else None
    vector = r.embedder.encode([args.query])[0][0]
    exclude = PLACEHOLDER_RULES if s.get("exclude_placeholders_from_dense") else None
    dense = r.store.dense_search(vector, s["top_k_dense"], allowed, r.index_version, exclude)
    sparse = r.bm25.search(args.query, s["top_k_sparse"], allowed)
    pool = rrf([dense, sparse])[:s["rerank_pool"]]
    reranked = r.reranker.rerank(args.query, [c for c, _ in pool], r.chunks)

    def title(chunk_id: str) -> str:
        c = r.chunks[chunk_id]
        return f"{c['citation']} ({c.get('section_title') or ''})"

    for name, ranking in (("dense", dense), ("bm25", sparse), ("rrf pool", pool), ("reranked", reranked)):
        print(f"\n== {name} (top {args.show})")
        for rank, (chunk_id, score) in enumerate(ranking[:args.show], start=1):
            print(f"{rank:3d}  {score:8.4f}  {title(chunk_id)}")

    if args.watch:
        print("\n== watched chunks")
        extra = dict(r.reranker.rerank(args.query, args.watch, r.chunks))
        cos = r.store.similarities(vector, args.watch, r.index_version)
        for chunk_id in args.watch:
            ranks = []
            for name, ranking in (("dense", dense), ("bm25", sparse), ("pool", pool), ("rerank", reranked)):
                ids = [c for c, _ in ranking]
                ranks.append(f"{name} {ids.index(chunk_id) + 1 if chunk_id in ids else '-'}")
            print(f"{chunk_id:16s} cos {cos.get(chunk_id, float('nan')):.4f}  rerank {extra[chunk_id]:.4f}  " + "  ".join(ranks))


if __name__ == "__main__":
    main()
