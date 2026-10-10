"""Cross-encoder reranking with bge-reranker-large.

The retrievers read the question and a chunk separately; the cross-encoder
reads them together, so it can tell "maternity leave" from "annual leave"
where both share most words. It is slower, so it only rescores a short
candidate list.

What it reads: citation + section title + content, the same text BM25
indexes. Without the citation it cannot match "section 60E" (measured
2026-10-10, plan `docs/plans/2026-10-10-m3-retrieval.md`, Section 3). This
is not an embedding, so the CP1 rule that only `content` is embedded is
unchanged.

The model reads at most 512 tokens for query and passage together, so a
long chunk is cut and its end is never scored. A long chunk is therefore
split into overlapping windows, each starting with the citation and title,
and the chunk scores as its best window.

The score (0 to 1 with normalize=True) means "this pair resembles the
relevant pairs seen in training". It is not a probability of being correct;
the abstention threshold is calibrated on labelled questions.
"""

from __future__ import annotations

MAX_LENGTH = 512
SPECIAL_TOKENS = 4  # <s> query </s></s> passage </s>
# Tokenizing header and content separately can differ by a token or two from
# tokenizing them joined; the margin keeps every window inside the limit.
SAFETY_MARGIN = 8


def passage(chunk: dict, text: str | None = None) -> str:
    """Citation, section title, then text (the chunk's content by default)."""
    body = chunk["content"] if text is None else text
    return " ".join(part for part in (chunk["citation"], chunk.get("section_title"), body) if part)


class Reranker:
    def __init__(self, model_name: str = "BAAI/bge-reranker-large", max_length: int = MAX_LENGTH,
                 safety_margin: int = SAFETY_MARGIN):
        self.model_name, self.max_length, self.safety_margin = model_name, max_length, safety_margin
        self._model = None

    def _load(self):
        if self._model is None:
            import torch
            from FlagEmbedding import FlagReranker

            self._model = FlagReranker(self.model_name, use_fp16=torch.cuda.is_available())
        return self._model

    def windows(self, query: str, chunk: dict) -> list[str]:
        """The passages scored for one chunk: one, or overlapping windows."""
        tokenizer = self._load().tokenizer
        count = lambda text: len(tokenizer.encode(text, add_special_tokens=False))  # noqa: E731
        header = count(passage(chunk, ""))
        budget = self.max_length - SPECIAL_TOKENS - count(query) - header - self.safety_margin
        budget = max(budget, self.max_length // 4)
        ids = tokenizer.encode(chunk["content"], add_special_tokens=False)
        if len(ids) <= budget:
            return [passage(chunk)]
        stride = max(1, budget // 2)
        starts = list(range(0, len(ids) - budget, stride)) + [len(ids) - budget]
        return [passage(chunk, tokenizer.decode(ids[start:start + budget])) for start in starts]

    def rerank(self, query: str, chunk_ids: list[str], chunks: dict[str, dict]) -> list[tuple[str, float]]:
        """Candidates re-ordered by cross-encoder score; ties by chunk_id."""
        if not chunk_ids:
            return []
        pairs, owners = [], []
        for chunk_id in chunk_ids:
            for text in self.windows(query, chunks[chunk_id]):
                pairs.append([query, text])
                owners.append(chunk_id)
        scores = self._load().compute_score(pairs, normalize=True, max_length=self.max_length)
        if isinstance(scores, float):
            scores = [scores]
        best: dict[str, float] = {}
        for chunk_id, score in zip(owners, map(float, scores)):
            best[chunk_id] = max(score, best.get(chunk_id, score))
        return sorted(best.items(), key=lambda item: (-item[1], item[0]))

    def close(self) -> None:
        if self._model is not None:
            import gc

            import torch

            self._model = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
