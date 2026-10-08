"""Cross-encoder reranking with bge-reranker-large.

The retrievers read the question and a chunk separately; the cross-encoder
reads them together, so it can tell "maternity leave" from "annual leave"
where both share most words. It is slower, so it only rescores a short
candidate list.

The score (0 to 1 with normalize=True) means "this pair resembles the
relevant pairs seen in training". It is not a probability of being correct;
the abstention threshold must be calibrated on the gold set (M3).
"""

from __future__ import annotations


class Reranker:
    def __init__(self, model_name: str = "BAAI/bge-reranker-large"):
        self.model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            import torch
            from FlagEmbedding import FlagReranker

            self._model = FlagReranker(self.model_name, use_fp16=torch.cuda.is_available())
        return self._model

    def rerank(self, query: str, chunk_ids: list[str], chunks: dict[str, dict]) -> list[tuple[str, float]]:
        """Candidates re-ordered by cross-encoder score; ties by chunk_id."""
        if not chunk_ids:
            return []
        scores = self._load().compute_score([[query, chunks[c]["content"]] for c in chunk_ids], normalize=True)
        if isinstance(scores, float):
            scores = [scores]
        return sorted(zip(chunk_ids, map(float, scores)), key=lambda item: (-item[1], item[0]))

    def close(self) -> None:
        if self._model is not None:
            import gc

            import torch

            self._model = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
