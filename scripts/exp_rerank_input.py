"""Experiment for M3 decision 2: what text should the reranker read?

    docker compose run --rm ml python scripts/exp_rerank_input.py

Part A. Reranker input "content" (as now) versus "citation + section title +
content" (what BM25 indexes). For each query the real hybrid pool (dense 20
+ BM25 20, RRF, top 20) is reranked both ways; the table shows where the
first expected chunk lands and the top score. Out-of-scope queries have no
expected chunk: for them the top score matters, because a prefix that lifts
nonsense scores would weaken the abstention gate.

Part B. The long chunks (over 350 words). bge-reranker-large reads at most
512 tokens for query and chunk together, so the end of a long chunk is cut.
For each chunk that is cut, a query is taken verbatim from the middle of the
cut-off tail and scored twice: against the normal (truncated) input and
against a 512-token window that contains the tail. A large gap means the
reranker cannot see the tail. A verbatim query is the easiest case for the
model, so the gap is a lower bound on the problem, not a typical value.

Not a test and not evaluation: a one-off measurement recorded in the devlog.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.indexing.bm25 import Bm25Index, index_text  # noqa: E402
from src.indexing.embed import BgeM3Embedder  # noqa: E402
from src.indexing.store import ChunkStore, connect  # noqa: E402
from src.retrieval.fusion import rrf  # noqa: E402
from src.retrieval.rerank import Reranker  # noqa: E402

POOL = 20
MAX_LEN = 512
SPECIAL = 4  # <s> query </s></s> passage </s>
LONG_WORDS = 350
TAIL_QUERY_TOKENS = 30

# (query, region, expected chunk_id prefixes); [] means out of scope.
QUERIES = [
    ("section 60E", None, ["EA1955_s60E"]),
    ("what does section 92 of the Employment Act say", "peninsular", ["EA1955_s92"]),
    ("section 20 of the Industrial Relations Act", None, ["IRA1967_s20"]),
    ("section 84 maternity leave", "sarawak", ["SWK76_s84", "A1754_s24"]),
    ("section 24 deductions from wages", "peninsular", ["EA1955_s24"]),
    ("how many days of annual leave am I entitled to", "peninsular", ["EA1955_s60E"]),
    ("how many days of maternity leave", "sabah", ["SBH67_s2_1_def_eligible_period", "SBH67_s83"]),
    ("maternity leave", "sarawak", ["SWK76_s84", "A1754_s24"]),
    ("can my employer dismiss me for joining a union", None, ["IRA1967_s5"]),
    ("how much notice must my employer give before terminating my contract", "peninsular", ["EA1955_s12"]),
    ("can my employer cut my salary", "peninsular", ["EA1955_s24"]),
    ("overtime pay for working on a rest day", "peninsular", ["EA1955_s60"]),
    ("can I bring my dog to work", None, []),
    ("nihao", None, []),
    ("what is the EPF contribution rate", None, []),
    ("how do I apply for a passport", None, []),
]


def matches(chunk_id: str, prefixes: list[str]) -> bool:
    return any(chunk_id == p or chunk_id.startswith(p + "_") for p in prefixes)


def first_hit(ranked: list[tuple[str, float]], prefixes: list[str]) -> tuple[int | None, float | None]:
    for rank, (chunk_id, score) in enumerate(ranked, start=1):
        if matches(chunk_id, prefixes):
            return rank, score
    return None, None


def fmt(rank: int | None, score: float | None) -> str:
    return "  miss     " if rank is None else f"#{rank:<2d} {score:.3f}"


def main() -> None:
    config = yaml.safe_load(Path("config/config.yaml").read_text(encoding="utf-8"))
    settings = config["indexing"]
    version = json.loads(Path(settings["manifest_path"]).read_text(encoding="utf-8"))["index_version"]
    chunks_path = Path(config["corpus"]["processed_dir"]) / "chunks.jsonl"
    chunks = {c["chunk_id"]: c for c in map(json.loads, chunks_path.open(encoding="utf-8"))}
    regions = config["retrieval"]["regions"]

    # Candidate pools first, then free bge-m3 before loading the reranker
    # (one model on the GPU at a time).
    embedder = BgeM3Embedder(settings["embedding_model"], settings["embed_batch_size"])
    bm25 = Bm25Index.load(settings["bm25_dir"])
    pools = []
    with connect(config) as conn:
        store = ChunkStore(conn, settings["embedding_dim"])
        for query, region, _ in QUERIES:
            allowed = regions[region] if region else None
            vector = embedder.encode([query])[0][0]
            dense = store.dense_search(vector, POOL, allowed, version)
            pools.append([c for c, _ in rrf([dense, bm25.search(query, POOL, allowed)])[:POOL]])
    embedder.close()

    reranker = Reranker()
    model = reranker._load()

    def score(pairs: list[list[str]]) -> list[float]:
        out = model.compute_score(pairs, normalize=True, max_length=MAX_LEN)
        return [float(out)] if isinstance(out, float) else [float(x) for x in out]

    def rerank(query: str, ids: list[str], text) -> list[tuple[str, float]]:
        scores = score([[query, text(chunks[c])] for c in ids])
        return sorted(zip(ids, scores), key=lambda item: (-item[1], item[0]))

    content = lambda c: c["content"]  # noqa: E731

    print("\nPART A: reranker input (first expected chunk: rank in reranked pool, score)")
    print(f"{'query':58s} {'region':10s} {'in pool':8s} {'content':12s} {'cite+title+content':18s} top score c / c+t+c")
    for (query, region, expected), pool in zip(QUERIES, pools):
        a = rerank(query, pool, content)
        b = rerank(query, pool, index_text)
        pool_rank, _ = first_hit([(c, 0.0) for c in pool], expected) if expected else (None, None)
        in_pool = "-" if not expected else (f"#{pool_rank}" if pool_rank else "no")
        cols = (fmt(*first_hit(a, expected)), fmt(*first_hit(b, expected))) if expected else ("-", "-")
        print(f"{query[:58]:58s} {region or 'all':10s} {in_pool:8s} {cols[0]:12s} {cols[1]:18s} "
              f"{a[0][1]:.3f} / {b[0][1]:.3f}  ({a[0][0]} / {b[0][0]})")

    print("\nPART B: long chunks (over 350 words)")
    tok = model.tokenizer
    long_chunks = [c for c in chunks.values() if len(c["content"].split()) > LONG_WORDS]
    print(f"{len(long_chunks)} chunks over {LONG_WORDS} words")
    budget = MAX_LEN - SPECIAL - TAIL_QUERY_TOKENS  # passage tokens visible next to the tail query
    rows = []
    for c in long_chunks:
        for label, text in (("content", content(c)), ("c+t+c", index_text(c))):
            ids = tok(text, add_special_tokens=False)["input_ids"]
            n = len(ids)
            if n <= budget:
                rows.append((c["chunk_id"], label, n, 0, None, None, ""))
                continue
            tail = n - budget
            start = budget + max(0, tail // 2 - TAIL_QUERY_TOKENS // 2)
            query = tok.decode(ids[start:start + TAIL_QUERY_TOKENS]).strip()
            window = tok.decode(ids[-budget:])
            truncated, windowed = score([[query, text], [query, window]])
            rows.append((c["chunk_id"], label, n, tail, truncated, windowed,
                         " ".join(tok.decode(ids[budget:budget + 25]).split())))
    print(f"{'chunk':34s} {'input':8s} {'tokens':>6s} {'cut':>5s} {'truncated':>9s} {'window':>7s}  tail starts")
    for chunk_id, label, n, cut, t, w, tail_text in sorted(rows, key=lambda r: (-r[3], r[0], r[1])):
        if cut == 0:
            print(f"{chunk_id:34s} {label:8s} {n:6d} {'fits':>5s}")
        else:
            print(f"{chunk_id:34s} {label:8s} {n:6d} {cut:5d} {t:9.3f} {w:7.3f}  {tail_text[:70]}")
    cut_rows = [r for r in rows if r[3] > 0]
    for label in ("content", "c+t+c"):
        mine = [r for r in cut_rows if r[1] == label]
        if mine:
            blind = sum(1 for r in mine if r[4] < 0.5 <= r[5])
            print(f"{label}: {len(mine)} chunks cut; truncated score < 0.5 while window >= 0.5 in {blind}")
    reranker.close()


if __name__ == "__main__":
    main()
