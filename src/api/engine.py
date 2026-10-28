"""The M5 engine: the loaded Retriever and Answerer behind the HTTP layer.

The API calls the same path the gold run used, with one fixed configuration
from config (mode hybrid_rerank, gate on); a client cannot change mode, gate
or threshold, so what users see is what the evaluation measured.

    retrieve   under a lock: bge-m3 and the reranker share one GPU
    answer     outside the lock: vLLM queues requests itself
    provision  the full chunk for the source panel, from the same chunks the
               index was built from

An expired OOD session drops the answerer, so the next request re-reads .env
and a fresh cookie works without a restart (as in scripts/ask.py).

Logs carry region, status and timings only, never query, answer or chunk
text (CLAUDE.md, Privacy and ethics).
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Callable

import yaml

from src.api.schema import Meta, Provision
from src.generation.llm import SessionExpired
from src.generation.prompt import PROMPT_VERSION
from src.generation.schema import DISCLAIMER, GeneratedAnswer
from src.retrieval.schema import RetrievalResult

log = logging.getLogger("getright.api")

WARM_UP_QUERY = "How many rest days does an employee get in a week?"


def _ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


class Engine:
    def __init__(self, retriever, answerer_factory: Callable[[], object], config: dict):
        self.retriever, self.config = retriever, config
        self._factory = answerer_factory
        self._answerer = None
        self._retrieve_lock = threading.Lock()
        self._answerer_lock = threading.Lock()
        # (doc_id, section) -> chunk ids in document order; chunks keep their file order.
        self._sections: dict[tuple, list[str]] = defaultdict(list)
        for chunk_id, chunk in retriever.chunks.items():
            if chunk.get("section") is not None:
                self._sections[(chunk.get("doc_id"), chunk["section"])].append(chunk_id)

    @classmethod
    def from_config(cls, config_path: str | Path = "config/config.yaml") -> "Engine":
        """Load bge-m3, the reranker and the index, and run one warm-up retrieval."""
        from dotenv import load_dotenv

        from src.generation.answer import Answerer
        from src.retrieval.pipeline import Retriever

        config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        retriever = Retriever.from_config(config_path)

        def factory():
            load_dotenv(override=True)  # pick up a fresh cookie pasted into .env
            return Answerer.from_config(config_path)

        engine = cls(retriever, factory, config)
        engine.retrieve(WARM_UP_QUERY, None)
        return engine

    def retrieve(self, query: str, region: str | None) -> RetrievalResult:
        with self._retrieve_lock:
            start = time.perf_counter()
            result = self.retriever.retrieve(query, region, self.config["api"]["retrieval_mode"], gate=True)
            log.info("retrieve region=%s abstained=%s reason=%s ms=%d",
                     region, result.abstained, result.abstain_reason, _ms(start))
        return result

    def _get_answerer(self):
        with self._answerer_lock:
            if self._answerer is None:
                self._answerer = self._factory()
            return self._answerer

    def answer(self, result: RetrievalResult) -> GeneratedAnswer:
        start = time.perf_counter()
        try:
            answer = self._get_answerer().answer(result)
        except SessionExpired:
            with self._answerer_lock:
                self._answerer = None
            raise
        log.info("answer region=%s status=%s ms=%d", result.region, answer.status, _ms(start))
        return answer

    def ask(self, query: str, region: str | None) -> GeneratedAnswer:
        return self.answer(self.retrieve(query, region))

    def provision(self, chunk_id: str) -> Provision | None:
        chunk = self.retriever.chunks.get(chunk_id)
        if chunk is None:
            return None
        siblings = self._sections.get((chunk.get("doc_id"), chunk.get("section")), [chunk_id])
        return Provision.from_chunk(chunk, list(siblings))

    def meta(self) -> Meta:
        return Meta(statutes_held=self.retriever.statutes_held, regions=self.config["retrieval"]["regions"],
                    disclaimer=DISCLAIMER, index_version=self.retriever.index_version,
                    prompt_version=PROMPT_VERSION, model=self.config["generation"]["model"])
