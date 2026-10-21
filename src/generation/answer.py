"""Answer a RetrievalResult (M4): prompt, one model call, typed result.

    gate abstained?  -> abstention notice, no model call
    otherwise        -> PROMPT | chat model   (a fixed LangChain LCEL chain)
                     -> markers resolved to citations from chunk metadata
                     -> GeneratedAnswer

No agent, no tools, no second retrieval: the same RetrievalResult always
gets the same prompt (CLAUDE.md: deterministic Advanced RAG).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml
from langchain_core.language_models import BaseChatModel

from src.generation.citations import resolve
from src.generation.llm import GeneratorError, build_chat_model, invoke_with_retry
from src.generation.prompt import INSUFFICIENT, PROMPT, PROMPT_VERSION, build_prompt
from src.generation.schema import Abstention, AnswerChecks, GeneratedAnswer, GeneratorInfo
from src.retrieval.schema import RetrievalResult


def abstention_message(reason: str, statutes_held: list[str]) -> str:
    message = ("This question is outside what GetRight can answer from the statutes it holds. GetRight covers:\n"
               + "".join(f"{statute}\n" for statute in statutes_held)
               + "For help with your situation, contact the Department of Labour (JTKSM, JTK Sabah or JTK Sarawak).")
    return ("GetRight answers questions in English only. " + message) if reason == "language" else message


class Answerer:
    def __init__(self, model: BaseChatModel, config: dict):
        self.settings = config["generation"]
        self.jurisdiction_notes = config.get("jurisdiction_notes") or {}
        self.caveats = {d["short_name"]: " ".join(d["currency_caveat"].split())
                        for d in config["corpus"]["documents"] if d.get("currency_caveat")}
        self.chain = PROMPT | model

    @classmethod
    def from_config(cls, config_path: str | Path = "config/config.yaml") -> "Answerer":
        from dotenv import load_dotenv

        load_dotenv()
        config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        return cls(build_chat_model(config["generation"], os.environ), config)

    def answer(self, result: RetrievalResult) -> GeneratedAnswer:
        base = dict(query=result.query, region=result.region, index_version=result.index_version)
        if result.abstained:
            notice = Abstention(reason=result.abstain_reason, statutes_held=result.statutes_held,
                                message=abstention_message(result.abstain_reason, result.statutes_held))
            return GeneratedAnswer(**base, status="abstained", answer=None, citations=[], abstention=notice, notes=[],
                                   external_dependencies=[], checks=AnswerChecks(), generator=None, context_chunk_ids=[])

        prompt = build_prompt(result, self.jurisdiction_notes)
        reply = invoke_with_retry(self.chain, prompt.variables, retries=self.settings["retries"])
        if not reply.text:
            raise GeneratorError(f"empty reply for {result.query!r}")
        generator = GeneratorInfo(model=reply.model or self.settings["model"], temperature=self.settings["temperature"],
                                  seed=self.settings["seed"], prompt_version=PROMPT_VERSION,
                                  finish_reason=reply.finish_reason, prompt_tokens=reply.prompt_tokens,
                                  completion_tokens=reply.completion_tokens)
        context_ids = [block.chunk_id for block in prompt.blocks]
        truncated = reply.finish_reason == "length"

        if re.sub(r"[\s.]+$", "", reply.text) == INSUFFICIENT:
            return GeneratedAnswer(**base, status="insufficient_context", answer=None, citations=[], abstention=None,
                                   notes=prompt.notes, external_dependencies=[], checks=AnswerChecks(truncated=truncated),
                                   generator=generator, context_chunk_ids=context_ids)

        resolved = resolve(reply.text, prompt.blocks)
        cited = {c.chunk_id for c in resolved.citations}
        cited_blocks = [block for block in prompt.blocks if block.chunk_id in cited]
        dependencies = sorted({ref for block in cited_blocks for ref in block.cross_references_external})
        caveats = list(dict.fromkeys(self.caveats[b.statute] for b in cited_blocks if b.statute in self.caveats))
        checks = AnswerChecks(invalid_markers=resolved.invalid_markers, uncited_sentences=resolved.uncited_sentences,
                              provision_mentions=resolved.provision_mentions, truncated=truncated)
        return GeneratedAnswer(**base, status="answered", answer=resolved.answer, citations=resolved.citations,
                               abstention=None, notes=prompt.notes + caveats, external_dependencies=dependencies,
                               checks=checks, generator=generator, context_chunk_ids=context_ids)
