"""Tests for src/api/engine.py, on fakes (no models, no database, no generator)."""
import logging
import threading

import pytest

from src.generation.llm import GeneratorError, SessionExpired
from src.generation.prompt import PROMPT_VERSION
from src.generation.schema import DISCLAIMER
from tests.unit.api_fakes import CONFIG, STATUTES, FakeAnswerer, engine_with


def test_ask_uses_configured_mode_with_gate():
    engine, retriever, _ = engine_with()
    engine.ask("q", "sabah")
    assert retriever.seen == [("q", "sabah", "hybrid_rerank", True)]


def test_retrieve_is_serialised():
    engine, retriever, _ = engine_with(delay=0.05)
    threads = [threading.Thread(target=engine.retrieve, args=("q", None)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert retriever.max_active == 1 and retriever.calls == 4


def test_answerer_built_once():
    engine, _, built = engine_with()
    for _ in range(3):
        engine.ask("q", None)
    assert len(built) == 1


def test_answerer_not_built_for_abstention():
    engine, _, built = engine_with()
    assert engine.ask("Berapa hari cuti?", None).status == "abstained"
    assert engine.ask("Berapa hari cuti?", None).abstention.reason == "language"
    assert len(built) <= 1


def test_session_expired_drops_answerer():
    engine, _, built = engine_with([FakeAnswerer(error=SessionExpired("cookie expired")), FakeAnswerer()])
    with pytest.raises(SessionExpired):
        engine.ask("q", None)
    assert engine.ask("q", None).status == "answered"
    assert len(built) == 2


def test_other_generator_error_keeps_answerer():
    engine, _, built = engine_with([FakeAnswerer(error=GeneratorError("server 500"))])
    for _ in range(2):
        with pytest.raises(GeneratorError):
            engine.ask("q", None)
    assert len(built) == 1


def test_provision_lists_section_siblings():
    engine, _, _ = engine_with()
    provision = engine.provision("EA1955_s59_2")
    assert provision.section_chunk_ids == ["EA1955_s59_1", "EA1955_s59_2"]
    assert provision.content.endswith("provided that the proviso stays.")
    assert provision.amended_by == []


def test_provision_unknown_is_none():
    engine, _, _ = engine_with()
    assert engine.provision("nope") is None


def test_meta():
    meta = engine_with()[0].meta()
    assert meta.statutes_held == STATUTES
    assert meta.regions == CONFIG["retrieval"]["regions"]
    assert meta.prompt_version == PROMPT_VERSION and meta.model == "Qwen/Qwen3-14B-AWQ"
    assert meta.index_version == "test-index" and meta.disclaimer == DISCLAIMER


def test_logs_never_contain_text(caplog):
    caplog.set_level(logging.DEBUG, logger="getright.api")
    engine, _, _ = engine_with()
    engine.ask("my employer withheld my overtime pay", "peninsular")
    assert "overtime" not in caplog.text
    assert "rest day" not in caplog.text and "EA1955" not in caplog.text
    assert "answered" in caplog.text and "peninsular" in caplog.text
