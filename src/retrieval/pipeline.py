"""The retrieval pipeline (M3): question and region in, RetrievalResult out.

    language gate -> dense + BM25 -> RRF -> reranker -> abstention gate
                  -> expansion (amendment links, same-section definitions)

A fixed sequence with no model choosing what to do next, so the same
question always gives the same chunks (CLAUDE.md: deterministic Advanced
RAG, no agentic retrieval).

Three modes run on the same code path, for the configuration comparison in
the evaluation plan:

    dense           dense ranking only;      gate on the top cosine
    hybrid          RRF of dense and BM25;   gate on the best cosine in its top k
    hybrid_rerank   RRF, then the reranker;  gate on the top reranker score

The RRF score is rank-based and nearly the same at the top for every query,
so it cannot gate; hybrid gates on the dense similarity of what it returns.
The language gate and expansion are identical in all modes.

The gate decides whether there is anything to answer from. It does not
check that a chunk legally supports an answer: the system measures
faithfulness to retrieved text, not legal correctness (CLAUDE.md, core
contribution 2).
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from src.retrieval.expand import Expander
from src.retrieval.fusion import rrf
from src.retrieval.schema import RetrievalResult, RetrievedChunk

MODES = ("dense", "hybrid", "hybrid_rerank")
PLACEHOLDER_RULES = ["placeholder", "range_placeholder"]
# Applies everywhere, so it never makes an answer territory-specific.
NATIONWIDE = "Malaysia"


class Retriever:
    def __init__(self, config: dict, chunks: dict[str, dict], embedder, store, bm25, reranker, language_gate,
                 index_version: str):
        """Components are injected so tests can use fakes. `chunks` in document order."""
        self.settings = config["retrieval"]
        self.chunks, self.index_version = chunks, index_version
        self.embedder, self.store, self.bm25, self.reranker = embedder, store, bm25, reranker
        self.language_gate = language_gate
        self.expander = Expander(chunks, max_chunks=self.settings["max_chunks"],
                                 reverse_cap=self.settings["reverse_amendment_cap"])
        self.statutes_held = [f"{d['short_name']} ({d['act_number']}), {d['jurisdiction_label']}"
                              for d in config["corpus"]["documents"]]

    @classmethod
    def from_config(cls, config_path: str | Path = "config/config.yaml") -> "Retriever":
        """The real pipeline: bge-m3, PostgreSQL, BM25, bge-reranker-large, lingua.

        Keeps bge-m3 and the reranker on the GPU together (about 2.5 GB),
        which fits the 8 GB development card; the generator is not loaded here.
        """
        from src.indexing.bm25 import Bm25Index
        from src.indexing.embed import BgeM3Embedder
        from src.indexing.store import ChunkStore, connect
        from src.retrieval.language import LanguageGate
        from src.retrieval.rerank import Reranker

        config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        indexing, settings = config["indexing"], config["retrieval"]
        manifest = json.loads(Path(indexing["manifest_path"]).read_text(encoding="utf-8"))
        chunks_path = Path(config["corpus"]["processed_dir"]) / "chunks.jsonl"
        chunks = {c["chunk_id"]: c for c in map(json.loads, chunks_path.open(encoding="utf-8"))}
        return cls(
            config, chunks,
            BgeM3Embedder(indexing["embedding_model"], indexing["embed_batch_size"]),
            ChunkStore(connect(config), indexing["embedding_dim"]),
            Bm25Index.load(indexing["bm25_dir"]),
            Reranker(settings["reranker_model"]),
            LanguageGate(**settings["language_gate"]),
            manifest["index_version"],
        )

    def _threshold(self, mode: str) -> float | None:
        thresholds = self.settings.get("abstention_threshold") or {}
        return thresholds.get(mode)

    def _rank(self, query: str, mode: str, allowed: list[str] | None) -> tuple[list[tuple[str, float]], float | None]:
        """The mode's top k (chunk_id, score) and its gate score."""
        s = self.settings
        vector = self.embedder.encode([query])[0][0]
        exclude = PLACEHOLDER_RULES if s.get("exclude_placeholders_from_dense") else None
        dense = self.store.dense_search(vector, s["top_k_dense"], allowed, self.index_version, exclude)
        k = s["top_k_final"]
        if mode == "dense":
            top = dense[:k]
            return top, (top[0][1] if top else None)
        fused = rrf([dense, self.bm25.search(query, s["top_k_sparse"], allowed)])[:s["rerank_pool"]]
        if mode == "hybrid":
            top = fused[:k]
            cosines = self.store.similarities(vector, [c for c, _ in top], self.index_version)
            return top, max(cosines.values(), default=None)
        top = self.reranker.rerank(query, [c for c, _ in fused], self.chunks)[:k]
        return top, (top[0][1] if top else None)

    def retrieve(self, query: str, region: str | None = None, mode: str = "hybrid_rerank",
                 gate: bool = True) -> RetrievalResult:
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode!r}; expected one of {MODES}")
        regions = self.settings["regions"]
        if region is not None and region not in regions:
            raise ValueError(f"unknown region {region!r}; expected one of {sorted(regions)} or None")
        allowed = regions[region] if region else None
        threshold = self._threshold(mode)
        base = dict(query=query, region=region, mode=mode, gate_enabled=gate, jurisdictions_searched=allowed,
                    threshold=threshold, statutes_held=self.statutes_held, index_version=self.index_version)

        def abstain(reason: str, language: str | None, score: float | None = None) -> RetrievalResult:
            return RetrievalResult(**base, jurisdictions_found=[], multiple_jurisdictions=False, abstained=True,
                                   abstain_reason=reason, detected_language=language, gate_score=score,
                                   chunks=[], expansions_dropped=0)

        language = self.language_gate.check(query)
        if not language.passed:
            return abstain("language", language.language)

        top, gate_score = self._rank(query, mode, allowed)
        if not top:
            return abstain("no_candidates", language.language)
        if gate and threshold is not None and gate_score < threshold:
            return abstain("low_score", language.language, gate_score)

        retrieved = [chunk_id for chunk_id, _ in top]
        expansion = self.expander.expand(retrieved, set(allowed) if allowed else None)
        items = [RetrievedChunk.from_chunk(self.chunks[c], score=score, rank=rank, added_because="retrieved")
                 for rank, (c, score) in enumerate(top, start=1)]
        items += [RetrievedChunk.from_chunk(self.chunks[a.chunk_id], added_because=a.added_because,
                                            linked_from=a.linked_from) for a in expansion.added]
        found = sorted({item.jurisdiction for item in items})
        territories = [j for j in found if j != NATIONWIDE]
        return RetrievalResult(**base, jurisdictions_found=found,
                               multiple_jurisdictions=region is None and len(territories) > 1,
                               abstained=False, abstain_reason=None, detected_language=language.language,
                               gate_score=gate_score, chunks=items, expansions_dropped=expansion.dropped)
