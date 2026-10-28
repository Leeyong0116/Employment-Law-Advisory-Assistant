"""Tests for src/api/app.py through FastAPI's TestClient, on fakes."""
import pytest
from fastapi.testclient import TestClient

from src.api.app import PUBLIC_MESSAGES, create_app
from src.generation.llm import EXPIRED_MESSAGE, GeneratorError, SessionExpired
from tests.unit.api_fakes import FakeAnswerer, engine_with


def _client(answerers=None):
    return TestClient(create_app(engine_with(answerers)[0]))


@pytest.fixture
def client():
    return _client()


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json() == {"status": "ok", "index_version": "test-index"}


def test_meta(client):
    body = client.get("/api/meta").json()
    assert set(body["regions"]) == {"peninsular", "sabah", "sarawak"} and len(body["statutes_held"]) == 2


def test_ask_answered(client):
    r = client.post("/api/ask", json={"query": "rest day", "region": "peninsular"})
    body = r.json()
    assert r.status_code == 200
    assert body["status"] == "answered" and body["citations"][0]["chunk_id"] == "EA1955_s59_1"
    assert body["answer"] and body["disclaimer"]


def test_ask_abstention_is_200(client):
    r = client.post("/api/ask", json={"query": "Berapa hari cuti bersalin?"})
    assert r.status_code == 200
    assert r.json()["status"] == "abstained" and r.json()["abstention"]["reason"] == "language"


def test_ask_blank_query_422(client):
    assert client.post("/api/ask", json={"query": "  "}).status_code == 422


def test_ask_bad_region_422(client):
    assert client.post("/api/ask", json={"query": "q", "region": "labuan"}).status_code == 422


def test_session_expired_503():
    r = _client([FakeAnswerer(error=SessionExpired(EXPIRED_MESSAGE))]).post("/api/ask", json={"query": "q"})
    assert r.status_code == 503
    assert r.json() == {"code": "generator_unavailable", "message": PUBLIC_MESSAGES["generator_unavailable"]}
    assert "cookie" not in r.text.lower() and ".env" not in r.text


def test_generator_error_502():
    r = _client([FakeAnswerer(error=GeneratorError("upstream 500 at http://internal"))]).post("/api/ask", json={"query": "q"})
    assert r.status_code == 502
    assert r.json() == {"code": "generator_error", "message": PUBLIC_MESSAGES["generator_error"]}
    assert "internal" not in r.text


def test_provision_found(client):
    r = client.get("/api/provisions/EA1955_s59_1")
    assert r.status_code == 200
    assert r.json()["content"] and r.json()["section_chunk_ids"] == ["EA1955_s59_1", "EA1955_s59_2"]
    assert "parse_rule" not in r.json()


def test_provision_missing_404(client):
    r = client.get("/api/provisions/nope")
    assert r.status_code == 404 and r.json() == {"code": "not_found", "message": PUBLIC_MESSAGES["not_found"]}


def test_cors_allows_dev_frontend(client):
    r = client.options("/api/ask", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_rejects_other_origin(client):
    r = client.options("/api/ask", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in r.headers
