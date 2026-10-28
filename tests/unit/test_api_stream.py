"""Tests for the stage stream (src/api/stream.py and POST /api/ask/stream), on fakes."""
import json

from fastapi.testclient import TestClient

from src.api.app import PUBLIC_MESSAGES, create_app
from src.generation.llm import SessionExpired
from tests.unit.api_fakes import FakeAnswerer, engine_with


def _client(answerers=None):
    return TestClient(create_app(engine_with(answerers)[0]))


def parse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def _stream(client, body):
    r = client.post("/api/ask/stream", json=body)
    return r, parse(r.text)


def test_answered_event_order():
    r, events = _stream(_client(), {"query": "rest day", "region": "peninsular"})
    assert r.status_code == 200
    assert [e for e, _ in events] == ["stage", "retrieval", "stage", "answer"]
    assert events[0][1] == {"stage": "retrieving"} and events[2][1] == {"stage": "generating"}
    assert events[1][1] == {"abstained": False, "abstain_reason": None,
                            "jurisdictions_found": ["Peninsular Malaysia and Labuan"], "multiple_jurisdictions": False}


def test_answer_event_equals_json_endpoint():
    client = _client()
    body = {"query": "rest day", "region": "peninsular"}
    _, events = _stream(client, body)
    assert events[-1][1] == client.post("/api/ask", json=body).json()


def test_abstained_skips_generating():
    _, events = _stream(_client(), {"query": "Berapa hari cuti bersalin?"})
    assert [e for e, _ in events] == ["stage", "retrieval", "answer"]
    assert events[1][1]["abstained"] is True and events[1][1]["abstain_reason"] == "language"
    assert events[-1][1]["status"] == "abstained"


def test_generator_failure_mid_stream():
    r, events = _stream(_client([FakeAnswerer(error=SessionExpired("cookie expired, edit .env"))]), {"query": "q"})
    assert r.status_code == 200
    assert [e for e, _ in events] == ["stage", "retrieval", "stage", "error"]
    assert events[-1][1] == {"code": "generator_unavailable", "message": PUBLIC_MESSAGES["generator_unavailable"]}
    assert "cookie" not in r.text


def test_unexpected_error_mid_stream():
    r, events = _stream(_client([FakeAnswerer(error=RuntimeError("boom at /secret/path"))]), {"query": "q"})
    assert events[-1] == ("error", {"code": "internal_error", "message": PUBLIC_MESSAGES["internal_error"]})
    assert "secret" not in r.text


def test_stream_validation_422():
    assert _client().post("/api/ask/stream", json={"query": "  "}).status_code == 422


def test_stream_content_type():
    r = _client().post("/api/ask/stream", json={"query": "q"})
    assert "text/event-stream" in r.headers["content-type"] and r.headers["cache-control"] == "no-cache"
