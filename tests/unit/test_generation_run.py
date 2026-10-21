"""Tests for src/generation/run.py."""
import json

import pytest

from src.generation.llm import SessionExpired
from src.generation.run import main, run
from src.generation.schema import AnswerChecks, GeneratedAnswer
from src.retrieval.schema import RetrievalResult


def _result(query):
    return RetrievalResult(
        query=query, region=None, mode="hybrid_rerank", gate_enabled=True, jurisdictions_searched=None,
        jurisdictions_found=[], multiple_jurisdictions=False, abstained=False, abstain_reason=None,
        detected_language="english", gate_score=0.9, threshold=0.0325, statutes_held=[], chunks=[],
        expansions_dropped=0, index_version="459843bf28ba",
    ).model_dump()


def _items(n):
    return [{"id": f"Q{i}", "result": _result(f"question {i}")} for i in range(1, n + 1)]


class FakeAnswerer:
    def __init__(self, expire_on=None):
        self.expire_on, self.seen = expire_on, []

    def answer(self, result):
        if result.query == self.expire_on:
            raise SessionExpired("OOD session expired")
        self.seen.append(result.query)
        return GeneratedAnswer(query=result.query, region=None, status="insufficient_context", answer=None, citations=[],
                               abstention=None, notes=[], external_dependencies=[], checks=AnswerChecks(),
                               generator=None, context_chunk_ids=[], index_version=result.index_version)


def _lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_writes_one_line_per_item(tmp_path):
    out = tmp_path / "answers.jsonl"
    assert run(_items(3), FakeAnswerer(), out) == 3
    lines = _lines(out)
    assert [line["id"] for line in lines] == ["Q1", "Q2", "Q3"]
    assert lines[0]["answer"]["query"] == "question 1"


def test_resume_skips_done_ids(tmp_path):
    out = tmp_path / "answers.jsonl"
    run(_items(2), FakeAnswerer(), out)
    answerer = FakeAnswerer()
    assert run(_items(4), answerer, out) == 2
    assert answerer.seen == ["question 3", "question 4"]
    assert [line["id"] for line in _lines(out)] == ["Q1", "Q2", "Q3", "Q4"]


def test_session_expired_keeps_written_lines(tmp_path):
    out = tmp_path / "answers.jsonl"
    with pytest.raises(SessionExpired):
        run(_items(4), FakeAnswerer(expire_on="question 3"), out)
    assert [line["id"] for line in _lines(out)] == ["Q1", "Q2"]
    assert run(_items(4), FakeAnswerer(), out) == 2
    assert [line["id"] for line in _lines(out)] == ["Q1", "Q2", "Q3", "Q4"]


def test_main_exits_2_on_session_expired(tmp_path, monkeypatch, capsys):
    source, out = tmp_path / "retrieval.jsonl", tmp_path / "answers.jsonl"
    source.write_text("".join(json.dumps(item) + "\n" for item in _items(3)), encoding="utf-8")
    monkeypatch.setattr("src.generation.run.Answerer.from_config", lambda *a, **k: FakeAnswerer(expire_on="question 2"))
    with pytest.raises(SystemExit) as stop:
        main([str(source), str(out)])
    assert stop.value.code == 2
    printed = capsys.readouterr().out
    assert "1 of 3 answered" in printed and "rerun the same command to continue" in printed
