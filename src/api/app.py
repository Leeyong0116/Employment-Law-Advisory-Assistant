"""The M5 FastAPI app: GetRight over HTTP.

    GET  /api/health                 status and index version
    GET  /api/meta                   statutes held, regions, disclaimer (abstention notice, Help page)
    POST /api/ask                    AskRequest -> GeneratedAnswer
    POST /api/ask/stream             the same, as server-sent pipeline stages (src/api/stream.py)
    GET  /api/provisions/{chunk_id}  full provision text for the source panel

The answer is returned as Answerer produced it: answer text and citations are
separate typed fields, and the API never edits either (CLAUDE.md, core
contribution 1). A citation points to the retrieved provision a statement came
from; it is traceability, not proof that the provision legally supports it.
An abstention is a normal 200 answer with status "abstained", not an error.

Generator failures get one fixed public message; the real detail (which may
name the cookie or .env) goes to the server log only.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from src.api.engine import Engine
from src.api.schema import ApiError, AskRequest, Meta, Provision
from src.generation.llm import GeneratorError, SessionExpired
from src.generation.schema import GeneratedAnswer

log = logging.getLogger("getright.api")

PUBLIC_MESSAGES = {
    "generator_unavailable": "The answer service is temporarily unavailable. Please try again in a few minutes.",
    "generator_error": "GetRight could not produce an answer this time. Please try again.",
    "not_found": "No provision with this id in the corpus.",
    "internal_error": "Something went wrong. Please try again.",
}


def _error(code: str) -> ApiError:
    return ApiError(code=code, message=PUBLIC_MESSAGES[code])


def error_for(exc: Exception) -> tuple[int, ApiError] | None:
    """The HTTP status and public error for a generator failure; None for anything else."""
    if isinstance(exc, SessionExpired):
        return 503, _error("generator_unavailable")
    if isinstance(exc, GeneratorError):
        return 502, _error("generator_error")
    return None


def create_app(engine: Engine) -> FastAPI:
    app = FastAPI(title="GetRight API", version="m5")
    app.state.engine = engine
    app.add_middleware(CORSMiddleware, allow_origins=engine.config["api"]["cors_origins"],
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

    @app.exception_handler(GeneratorError)
    def _generator_failed(request: Request, exc: GeneratorError):
        status, error = error_for(exc)
        log.warning("generator failure code=%s detail=%s", error.code, exc)
        return JSONResponse(status_code=status, content=error.model_dump())

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "index_version": engine.retriever.index_version}

    @app.get("/api/meta", response_model=Meta)
    def meta() -> Meta:
        return engine.meta()

    # Plain def: FastAPI runs it in its threadpool, so a 10 to 30 s generator call does not block the loop.
    @app.post("/api/ask", response_model=GeneratedAnswer)
    def ask(request: AskRequest) -> GeneratedAnswer:
        return engine.ask(request.query, request.region)

    @app.post("/api/ask/stream")
    def ask_stream(request: AskRequest) -> StreamingResponse:
        from src.api.stream import ask_events  # stream imports this module

        return StreamingResponse(ask_events(engine, request), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    @app.get("/api/provisions/{chunk_id}", response_model=Provision,
             responses={404: {"model": ApiError}})
    def provision(chunk_id: str):
        found = engine.provision(chunk_id)
        if found is None:
            return JSONResponse(status_code=404, content=_error("not_found").model_dump())
        return found

    return app


def build() -> FastAPI:
    """The uvicorn factory: `uvicorn src.api.app:build --factory`. Loads the models once."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return create_app(Engine.from_config())
