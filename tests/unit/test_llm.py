"""Tests for src/generation/llm.py: the real ChatOpenAI over a fake HTTP transport."""
import json

import httpx
import pytest

from src.generation.llm import GeneratorError, SessionExpired, build_chat_model, invoke_with_retry, list_models

COOKIE = "mod_auth_openidc_session=secret-value-123"
ENV = {"GENERATOR_BASE_URL": "https://ood.example/rnode/node1/8000/v1", "OOD_COOKIE_SECRET": COOKIE}
SETTINGS = {
    "base_url_env": "GENERATOR_BASE_URL", "cookie_env": "OOD_COOKIE_SECRET", "api_key_env": None,
    "model": "Qwen/Qwen3-14B-AWQ", "temperature": 0, "seed": 0, "max_tokens": 1024, "enable_thinking": False,
    "timeout_seconds": 120, "retries": 3,
}
MESSAGES = [("system", "rules"), ("human", "question")]


def _completion(text="Eight days [1].", finish_reason="stop"):
    return {
        "id": "x", "object": "chat.completion", "created": 0, "model": "Qwen/Qwen3-14B-AWQ",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 8, "total_tokens": 108},
    }


class Recorder:
    def __init__(self, *responses):
        self.responses, self.requests = list(responses), []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        return response


def _model(recorder):
    return build_chat_model(SETTINGS, ENV, transport=httpx.MockTransport(recorder))


def _invoke(recorder, sleeps=None):
    return invoke_with_retry(_model(recorder), MESSAGES, retries=3, sleep=(sleeps.append if sleeps is not None else lambda s: None))


def test_sends_cookie_and_body():
    rec = Recorder(httpx.Response(200, json=_completion()))
    _invoke(rec)
    request = rec.requests[0]
    assert str(request.url) == "https://ood.example/rnode/node1/8000/v1/chat/completions"
    assert request.headers["cookie"] == COOKIE
    body = json.loads(request.content)
    assert body["model"] == "Qwen/Qwen3-14B-AWQ"
    assert body["temperature"] == 0 and body["seed"] == 0
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body.get("max_tokens", body.get("max_completion_tokens")) == 1024


def test_reply_fields():
    reply = _invoke(Recorder(httpx.Response(200, json=_completion())))
    assert (reply.text, reply.model, reply.finish_reason) == ("Eight days [1].", "Qwen/Qwen3-14B-AWQ", "stop")
    assert (reply.prompt_tokens, reply.completion_tokens) == (100, 8)


def test_redirect_to_login_raises_session_expired():
    rec = Recorder(httpx.Response(302, headers={"location": "https://ood.example/oidc?login"}))
    with pytest.raises(SessionExpired):
        _invoke(rec)
    assert len(rec.requests) == 1


def test_html_200_raises_session_expired():
    rec = Recorder(httpx.Response(200, text="<html><body>Sign in</body></html>", headers={"content-type": "text/html"}))
    with pytest.raises(SessionExpired):
        _invoke(rec)
    assert len(rec.requests) == 1


def test_retries_5xx_then_fails():
    rec, sleeps = Recorder(httpx.Response(503, json={"error": "busy"})), []
    with pytest.raises(GeneratorError):
        _invoke(rec, sleeps)
    assert len(rec.requests) == 4
    assert sleeps == [2, 4, 8]


def test_5xx_then_success():
    rec = Recorder(httpx.Response(502, json={"error": "bad gateway"}), httpx.Response(200, json=_completion()))
    assert _invoke(rec).text == "Eight days [1]."
    assert len(rec.requests) == 2


def test_html_5xx_from_proxy_is_retried_not_session_expired():
    page = httpx.Response(503, text="<html><body>Service Unavailable</body></html>", headers={"content-type": "text/html"})
    rec, sleeps = Recorder(page), []
    with pytest.raises(GeneratorError) as raised:
        _invoke(rec, sleeps)
    assert not isinstance(raised.value, SessionExpired)
    assert len(rec.requests) == 4 and sleeps == [2, 4, 8]


def test_html_502_then_success():
    page = httpx.Response(502, text="<html>Bad Gateway</html>", headers={"content-type": "text/html"})
    assert _invoke(Recorder(page, httpx.Response(200, json=_completion()))).text == "Eight days [1]."


def test_client_error_not_retried():
    rec = Recorder(httpx.Response(400, json={"error": {"message": "prompt too long"}}))
    with pytest.raises(GeneratorError):
        _invoke(rec)
    assert len(rec.requests) == 1


def test_think_block_stripped():
    rec = Recorder(httpx.Response(200, json=_completion("<think>\nLet me see.\n</think>\n\nEight days [1].")))
    assert _invoke(rec).text == "Eight days [1]."


def test_finish_reason_length_reported():
    assert _invoke(Recorder(httpx.Response(200, json=_completion(finish_reason="length")))).finish_reason == "length"


def test_secret_not_in_repr():
    model = _model(Recorder(httpx.Response(200, json=_completion())))
    assert "secret-value-123" not in repr(model)
    assert "secret-value-123" not in str(model.model_dump())


def test_list_models():
    rec = Recorder(httpx.Response(200, json={"object": "list", "data": [{"id": "Qwen/Qwen3-14B-AWQ"}]}))
    assert list_models(SETTINGS, ENV, transport=httpx.MockTransport(rec)) == ["Qwen/Qwen3-14B-AWQ"]
    assert rec.requests[0].headers["cookie"] == COOKIE


def test_list_models_redirect_raises_session_expired():
    rec = Recorder(httpx.Response(302, headers={"location": "https://ood.example/oidc?login"}))
    with pytest.raises(SessionExpired):
        list_models(SETTINGS, ENV, transport=httpx.MockTransport(rec))


def test_missing_base_url_is_a_clear_error():
    with pytest.raises(GeneratorError, match="GENERATOR_BASE_URL"):
        build_chat_model(SETTINGS, {}, transport=httpx.MockTransport(Recorder(httpx.Response(200))))
