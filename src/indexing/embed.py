"""bge-m3 embeddings: one pass gives the dense vector and the sparse weights.

The model is loaded on first use and released by close(), so only one model
holds GPU memory at a time (CLAUDE.md hardware rule).
"""

from __future__ import annotations


class BgeM3Embedder:
    def __init__(self, model_name: str = "BAAI/bge-m3", batch_size: int = 16, max_length: int = 8192):
        self.model_name, self.batch_size, self.max_length = model_name, batch_size, max_length
        self._model = None

    def _load(self):
        if self._model is None:
            import torch
            from FlagEmbedding import BGEM3FlagModel

            self._model = BGEM3FlagModel(self.model_name, use_fp16=torch.cuda.is_available())
        return self._model

    def encode(self, texts: list[str]) -> tuple[list[list[float]], list[dict[str, float]]]:
        """Dense vectors (unit length, 1,024 dims) and sparse token weights."""
        output = self._load().encode(
            texts, batch_size=self.batch_size, max_length=self.max_length,
            return_dense=True, return_sparse=True, return_colbert_vecs=False,
        )
        dense = [[float(x) for x in vector] for vector in output["dense_vecs"]]
        sparse = [{str(k): float(v) for k, v in weights.items()} for weights in output["lexical_weights"]]
        return dense, sparse

    def close(self) -> None:
        if self._model is not None:
            import gc

            import torch

            self._model = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
