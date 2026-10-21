"""The chat model behind generation (M4): one interface, chosen by config.

Any OpenAI-compatible server works: vLLM on the Sunway HPC behind the Open
OnDemand proxy (authenticated by the browser session cookie), a hosted API
(Bearer key), or a local server. Switching is a config change, not a code
change (CLAUDE.md, hardware rules).

The OOD proxy answers an expired session with its login page, as a redirect
or as an HTML page. An httpx response hook turns either into SessionExpired,
which is never retried, so a batch run stops cleanly instead of saving a
login page as an answer. Retries are done here, not by the openai SDK, so
they can be counted and tested.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping

import httpx
import openai
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)
REDIRECTS = {301, 302, 303, 307, 308}
EXPIRED_MESSAGE = "OOD session expired: copy a fresh cookie into .env (OOD_COOKIE_SECRET) and rerun"


class GeneratorError(RuntimeError):
    pass


class SessionExpired(GeneratorError):
    pass


class Reply(BaseModel):
    text: str
    model: str
    finish_reason: str | None
    prompt_tokens: int | None
    completion_tokens: int | None


def _value(settings: dict, env: Mapping[str, str], key: str) -> str | None:
    name = settings.get(key)
    if not name:
        return None
    value = (env.get(name) or "").strip().strip('"').strip("'")
    if not value:
        raise GeneratorError(f"{name} is not set; add it to .env")
    return value


def _check_login(response: httpx.Response) -> None:
    """httpx response hook: the OOD login page, as a redirect or as an HTML page, means the session expired."""
    if response.status_code in REDIRECTS or response.status_code == 401 \
            or "text/html" in response.headers.get("content-type", ""):
        raise SessionExpired(EXPIRED_MESSAGE)


def _client(settings: dict, env: Mapping[str, str], transport: httpx.BaseTransport | None) -> httpx.Client:
    cookie = _value(settings, env, "cookie_env")
    return httpx.Client(headers={"Cookie": cookie} if cookie else {}, follow_redirects=False, transport=transport,
                        timeout=settings["timeout_seconds"], event_hooks={"response": [_check_login]})


def build_chat_model(settings: dict, env: Mapping[str, str], transport: httpx.BaseTransport | None = None) -> BaseChatModel:
    """ChatOpenAI for the configured server. The cookie rides on the HTTP client, not on the model,
    so it never shows in the model's repr or dump."""
    base_url = _value(settings, env, "base_url_env").rstrip("/")
    return ChatOpenAI(
        model=settings["model"],
        base_url=base_url,
        api_key=_value(settings, env, "api_key_env") or "EMPTY",
        temperature=settings["temperature"],
        seed=settings["seed"],
        max_tokens=settings["max_tokens"],
        timeout=settings["timeout_seconds"],
        max_retries=0,
        http_client=_client(settings, env, transport),
        extra_body={"chat_template_kwargs": {"enable_thinking": settings["enable_thinking"]}},
    )


def invoke_with_retry(model: BaseChatModel, messages, retries: int, sleep: Callable[[float], None] = time.sleep) -> Reply:
    """One chat completion. A login page raises SessionExpired at once; 5xx and connection
    errors are retried with 2, 4, 8 ... s backoff, then raise GeneratorError."""
    for attempt in range(retries + 1):
        try:
            message = model.invoke(messages)
        except openai.APIStatusError as error:
            if error.status_code < 500 or attempt == retries:
                raise GeneratorError(f"generator returned HTTP {error.status_code}: {error.message}") from error
        except openai.APIConnectionError as error:
            # The openai SDK wraps exceptions raised in the httpx hook.
            if isinstance(error.__cause__, SessionExpired):
                raise error.__cause__ from None
            if attempt == retries:
                raise GeneratorError(f"generator unreachable after {retries + 1} attempts: {error}") from error
        else:
            metadata, usage = message.response_metadata, message.usage_metadata or {}
            return Reply(
                text=THINK_BLOCK.sub("", message.content).strip(),
                model=metadata.get("model_name") or "",
                finish_reason=metadata.get("finish_reason"),
                prompt_tokens=usage.get("input_tokens"),
                completion_tokens=usage.get("output_tokens"),
            )
        sleep(2 ** (attempt + 1))
    raise AssertionError("unreachable")


def list_models(settings: dict, env: Mapping[str, str], transport: httpx.BaseTransport | None = None) -> list[str]:
    """Model ids the server reports at /models."""
    base_url = _value(settings, env, "base_url_env").rstrip("/")
    with _client(settings, env, transport) as client:
        response = client.get(f"{base_url}/models")
    response.raise_for_status()
    return [model["id"] for model in response.json()["data"]]
