"""Pipeline stages as server-sent events (plan 2026-10-28, D1).

    stage      {"stage": "retrieving"}
    retrieval  gate outcome
    stage      {"stage": "generating"}     only when the gate passed
    answer     GeneratedAnswer             last event on success
    error      ApiError                    last event on failure

Stages, not tokens: Answerer renumbers markers, removes invalid ones and
detects INSUFFICIENT_CONTEXT only after the full reply, so streamed tokens
would show text and citations the final answer then changes. Every citation
the user sees is still a checked one.

Headers are sent before generation runs, so a failure cannot change the HTTP
status; it ends the stream with an error event instead.
"""

from __future__ import annotations

import json
import logging
from typing import Iterator

from pydantic import BaseModel

from src.api.app import PUBLIC_MESSAGES, error_for
from src.api.engine import Engine
from src.api.schema import ApiError, AskRequest

log = logging.getLogger("getright.api")


def sse(event: str, data: dict | BaseModel) -> str:
    payload = data.model_dump_json() if isinstance(data, BaseModel) else json.dumps(data)
    return f"event: {event}\ndata: {payload}\n\n"


def ask_events(engine: Engine, request: AskRequest) -> Iterator[str]:
    try:
        yield sse("stage", {"stage": "retrieving"})
        result = engine.retrieve(request.query, request.region)
        yield sse("retrieval", {"abstained": result.abstained, "abstain_reason": result.abstain_reason,
                                "jurisdictions_found": result.jurisdictions_found,
                                "multiple_jurisdictions": result.multiple_jurisdictions})
        if not result.abstained:
            yield sse("stage", {"stage": "generating"})
        yield sse("answer", engine.answer(result))
    except Exception as exc:  # the stream has started: report in-band, never cut the connection
        mapped = error_for(exc)
        if mapped is None:
            log.exception("stream failed")
            error = ApiError(code="internal_error", message=PUBLIC_MESSAGES["internal_error"])
        else:
            error = mapped[1]
            log.warning("generator failure code=%s detail=%s", error.code, exc)
        yield sse("error", error)
