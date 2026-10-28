"""Fakes for the M5 API tests: no models, no database, no generator server."""
from __future__ import annotations

import threading
import time

from src.api.engine import Engine
from src.generation.schema import Abstention, AnswerChecks, Citation, GeneratedAnswer
from src.retrieval.schema import RetrievalResult, RetrievedChunk

EA, SBH = "Peninsular Malaysia and Labuan", "Sabah"
STATUTES = ["Employment Act 1955 (Act 265), Peninsular Malaysia and Labuan",
            "Labour Ordinance (Sabah) (Cap. 67), Sabah"]
INDEX = "test-index"


def _chunk(chunk_id, doc_id, section, subsection, jurisdiction=EA, statute="Employment Act 1955"):
    return {"chunk_id": chunk_id, "doc_id": doc_id, "statute": statute, "act_number": "Act 265",
            "part": "Part XII", "part_title": None, "section": section, "section_title": "Rest day",
            "subsection": subsection, "citation": f"{statute}, s. {section}{subsection or ''}",
            "chunk_type": "provision", "jurisdiction": jurisdiction, "status": "in_force", "deleted_by": None,
            "content": f"{chunk_id} text, provided that the proviso stays.", "source_page": 53,
            "source_page_end": 53, "source_url": "https://lom.agc.gov.my/", "source_version": "as at 1 January 2023",
            "cross_references_internal": [], "cross_references_external": None, "in_force_notes": None,
            "amended_by": None, "amends": None, "parse_rule": "subsection", "row_id": None}


# In document order, as the Retriever holds them.
CHUNKS = {c["chunk_id"]: c for c in [
    _chunk("EA1955_s59_1", "employment_act_1955", "59", "(1)"),
    _chunk("EA1955_s59_2", "employment_act_1955", "59", "(2)"),
    _chunk("EA1955_s60_1", "employment_act_1955", "60", "(1)"),
    _chunk("SBH_s59_1", "labour_ordinance_sabah", "59", "(1)", SBH, "Labour Ordinance (Sabah)"),
]}

CONFIG = {
    "retrieval": {"regions": {"peninsular": [EA, "Malaysia"], "sabah": [SBH, "Malaysia"],
                              "sarawak": ["Sarawak", "Malaysia"]}},
    "generation": {"model": "Qwen/Qwen3-14B-AWQ"},
    "api": {"retrieval_mode": "hybrid_rerank", "cors_origins": ["http://localhost:5173"]},
}


def retrieval_result(query, region=None, abstained=False, reason=None) -> RetrievalResult:
    chunks = [] if abstained else [RetrievedChunk.from_chunk(CHUNKS["EA1955_s59_1"], score=0.9, rank=1,
                                                             added_because="retrieved")]
    return RetrievalResult(
        query=query, region=region, mode="hybrid_rerank", gate_enabled=True, jurisdictions_searched=None,
        jurisdictions_found=[] if abstained else [EA], multiple_jurisdictions=False, abstained=abstained,
        abstain_reason=reason, detected_language=None if reason == "language" else "english",
        gate_score=None if abstained else 0.9, threshold=0.0325, statutes_held=STATUTES, chunks=chunks,
        expansions_dropped=0, index_version=INDEX)


def generated(result: RetrievalResult) -> GeneratedAnswer:
    base = dict(query=result.query, region=result.region, notes=[], external_dependencies=[],
                checks=AnswerChecks(), index_version=result.index_version)
    if result.abstained:
        notice = Abstention(reason=result.abstain_reason, statutes_held=result.statutes_held, message="out of scope")
        return GeneratedAnswer(**base, status="abstained", answer=None, citations=[], abstention=notice,
                               generator=None, context_chunk_ids=[])
    first = result.chunks[0]
    return GeneratedAnswer(**base, status="answered", answer="Every employee gets one rest day a week [1].",
                           citations=[Citation.from_chunk(1, first)], abstention=None, generator=None,
                           context_chunk_ids=[first.chunk_id])


class FakeRetriever:
    """Answers abstained (reason "language") when the query starts with "Berapa", else answered."""

    def __init__(self, chunks: dict = CHUNKS, delay: float = 0):
        self.chunks, self.delay = chunks, delay
        self.statutes_held, self.index_version = STATUTES, INDEX
        self.calls, self.seen, self.active, self.max_active = 0, [], 0, 0
        self._count = threading.Lock()

    def retrieve(self, query, region=None, mode="hybrid_rerank", gate=True):
        with self._count:
            self.calls += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.seen.append((query, region, mode, gate))
        time.sleep(self.delay)
        with self._count:
            self.active -= 1
        if query.startswith("Berapa"):
            return retrieval_result(query, region, abstained=True, reason="language")
        return retrieval_result(query, region)


class FakeAnswerer:
    def __init__(self, error: Exception | None = None):
        self.error = error

    def answer(self, result):
        if self.error is not None and not result.abstained:
            raise self.error
        return generated(result)


def engine_with(answerers: list | None = None, delay: float = 0) -> tuple[Engine, FakeRetriever, list]:
    """An engine on fakes. `answerers` are handed out by the factory in order; the list of built ones is returned."""
    queue = list(answerers or [FakeAnswerer()])
    built = []

    def factory():
        answerer = queue.pop(0) if len(queue) > 1 else queue[0]
        built.append(answerer)
        return answerer

    retriever = FakeRetriever(delay=delay)
    return Engine(retriever, factory, CONFIG), retriever, built
