"""Tests for src/generation/answer.py, with LangChain's fake chat model (no server)."""
from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from src.generation.answer import Answerer, abstention_message
from src.generation.prompt import PROMPT_VERSION
from src.retrieval.schema import RetrievalResult, RetrievedChunk

EA, SWK = "Peninsular Malaysia and Labuan", "Sarawak"

CONFIG = {
    "corpus": {"documents": [
        {"short_name": "Employment Act 1955", "jurisdiction_label": EA},
        {"short_name": "Labour Ordinance (Sarawak)", "jurisdiction_label": SWK,
         "currency_caveat": "The text held here incorporates amendments only up to 31 July 2006.\n"},
    ]},
    "jurisdiction_notes": {"sarawak": [{"note": "Act A1754 section 2 substituted worker with employee."}]},
    "generation": {"model": "Qwen/Qwen3-14B-AWQ", "temperature": 0, "seed": 0, "retries": 3},
}


class CountingFake(GenericFakeChatModel):
    calls: int = 0

    def _generate(self, *args, **kwargs):
        self.calls += 1
        return super()._generate(*args, **kwargs)


def _fake(text, finish_reason="stop"):
    message = AIMessage(content=text, response_metadata={"finish_reason": finish_reason, "model_name": "Qwen/Qwen3-14B-AWQ"},
                        usage_metadata={"input_tokens": 900, "output_tokens": 40, "total_tokens": 940})
    return CountingFake(messages=iter([message]))


def _chunk(chunk_id, jurisdiction=EA, statute="Employment Act 1955", **fields):
    return RetrievedChunk(**{"chunk_id": chunk_id, "citation": f"{statute}, {chunk_id}", "statute": statute,
                             "chunk_type": "provision", "jurisdiction": jurisdiction, "status": "in_force",
                             "content": f"{chunk_id} text", "added_because": "retrieved", **fields})


def _result(chunks, abstained=False, reason=None, region="peninsular"):
    return RetrievalResult(
        query="How many days of annual leave?", region=region, mode="hybrid_rerank", gate_enabled=True,
        jurisdictions_searched=None, jurisdictions_found=[], multiple_jurisdictions=False, abstained=abstained,
        abstain_reason=reason, detected_language="english", gate_score=0.9, threshold=0.0325,
        statutes_held=["Employment Act 1955 (Act 265), Peninsular Malaysia and Labuan", "Industrial Relations Act 1967 (Act 177), Malaysia"],
        chunks=chunks, expansions_dropped=0, index_version="459843bf28ba",
    )


def test_abstained_result_makes_no_call():
    model = _fake("should not be used")
    answer = Answerer(model, CONFIG).answer(_result([], abstained=True, reason="low_score"))
    assert model.calls == 0
    assert answer.status == "abstained" and answer.answer is None and answer.generator is None
    assert answer.abstention.reason == "low_score"
    assert answer.abstention.statutes_held == _result([]).statutes_held
    assert answer.abstention.message == abstention_message("low_score", _result([]).statutes_held)


def test_abstention_message_text():
    message = abstention_message("low_score", ["Employment Act 1955 (Act 265), Peninsular Malaysia and Labuan"])
    assert message == ("This question is outside what GetRight can answer from the statutes it holds. GetRight covers:\n"
                       "Employment Act 1955 (Act 265), Peninsular Malaysia and Labuan\n"
                       "For help with your situation, contact the Department of Labour (JTKSM, JTK Sabah or JTK Sarawak).")


def test_language_abstention_says_english_only():
    assert abstention_message("language", ["X"]).startswith("GetRight answers questions in English only. ")


def test_answered_fields():
    chunks = [_chunk("EA1955_s60E_1"), _chunk("EA1955_s60E_2")]
    model = _fake("You get eight days a year in your first two years of service [2].")
    answer = Answerer(model, CONFIG).answer(_result(chunks))
    assert model.calls == 1
    assert answer.status == "answered"
    assert answer.answer == "You get eight days a year in your first two years of service [1]."
    assert [(c.number, c.chunk_id) for c in answer.citations] == [(1, "EA1955_s60E_2")]
    assert answer.context_chunk_ids == ["EA1955_s60E_1", "EA1955_s60E_2"]
    assert answer.index_version == "459843bf28ba"
    assert (answer.generator.model, answer.generator.prompt_version, answer.generator.prompt_tokens) == (
        "Qwen/Qwen3-14B-AWQ", PROMPT_VERSION, 900)


def test_insufficient_context_status():
    answer = Answerer(_fake("INSUFFICIENT_CONTEXT"), CONFIG).answer(_result([_chunk("EA1955_s60E_1")]))
    assert answer.status == "insufficient_context"
    assert answer.answer is None and answer.citations == []


def test_insufficient_context_with_trailing_full_stop():
    assert Answerer(_fake("INSUFFICIENT_CONTEXT."), CONFIG).answer(_result([_chunk("X_1")])).status == "insufficient_context"


def test_sentinel_after_explanation_is_insufficient_context():
    reply = "The sources do not say how much rent may be charged. INSUFFICIENT_CONTEXT"
    answer = Answerer(_fake(reply), CONFIG).answer(_result([_chunk("X_1")]))
    assert answer.status == "insufficient_context"
    assert answer.answer is None and answer.citations == []


def test_sentinel_before_explanation_is_insufficient_context():
    reply = "INSUFFICIENT_CONTEXT\n\nThe sources only cover annual leave [1]."
    assert Answerer(_fake(reply), CONFIG).answer(_result([_chunk("X_1")])).status == "insufficient_context"


def test_non_current_citations_flagged():
    chunks = [_chunk("A1754_s52_122J", "Sarawak", "Labour Ordinance of Sarawak (Amendment) Act 2025", status="not_yet_in_force"),
              _chunk("SWK76_s75A_4", "Sarawak", "Labour Ordinance (Sarawak)", status="deleted"),
              _chunk("SWK76_s8_1", "Sarawak", "Labour Ordinance (Sarawak)")]
    answer = Answerer(_fake("Rent rules exist [1]. Minimum rates applied [2]. Contracts must be written [3]."),
                      CONFIG).answer(_result(chunks, region="sarawak"))
    assert answer.checks.non_current_citations == ["A1754_s52_122J", "SWK76_s75A_4"]


def test_superseded_cited_without_its_amendment_is_non_current():
    chunks = [_chunk("SWK76_s84_1", "Sarawak", "Labour Ordinance (Sarawak)", status="superseded", amended_by=["A1754_s24"]),
              _chunk("A1754_s24", "Sarawak", "Labour Ordinance of Sarawak (Amendment) Act 2025")]
    alone = Answerer(_fake("Maternity leave is sixty days [1]."), CONFIG).answer(_result(chunks, region="sarawak"))
    paired = Answerer(_fake("Maternity leave is ninety-eight days [1][2]."), CONFIG).answer(_result(chunks, region="sarawak"))
    assert alone.checks.non_current_citations == ["SWK76_s84_1"]
    assert paired.checks.non_current_citations == []


def test_external_dependencies_from_cited_chunks_only():
    chunks = [_chunk("EA1955_s60J_1", cross_references_external=["Termination Regulations"]),
              _chunk("EA1955_s2_1", cross_references_external=["Minimum Wages Order"])]
    answer = Answerer(_fake("Benefits are paid on termination of the contract [1]."), CONFIG).answer(_result(chunks))
    assert answer.external_dependencies == ["Termination Regulations"]


def test_notes_include_jurisdiction_note_and_cited_statute_caveat():
    chunks = [_chunk("SWK76_s84_1", SWK, "Labour Ordinance (Sarawak)")]
    answer = Answerer(_fake("Maternity leave is ninety-eight days [1]."), CONFIG).answer(_result(chunks, region="sarawak"))
    assert answer.notes == ["Act A1754 section 2 substituted worker with employee.",
                            "The text held here incorporates amendments only up to 31 July 2006."]


def test_checks_filled():
    answer = Answerer(_fake("Under section 60E you get eight days [1]. A long sentence with no marker here at all.", "length"),
                      CONFIG).answer(_result([_chunk("X_1")]))
    assert answer.checks.truncated is True
    assert answer.checks.provision_mentions == ["section 60E"]
    assert answer.checks.uncited_sentences == 1
