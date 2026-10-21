"""Typed output of generation (M4).

The answer text and the citations are separate fields. Every citation is
copied from the metadata of a chunk the model was shown, never from text the
model wrote (CLAUDE.md, core contribution 1). The model only writes markers
like [1]; src/generation/citations.py maps them back to chunks.

A citation shows where a statement came from. It does not show that the
provision legally supports the statement: the system measures traceability
and faithfulness, not legal correctness (CLAUDE.md, core contribution 2).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, model_validator

from src.retrieval.schema import AbstainReason, RetrievedChunk

# answered              the model answered from the context
# abstained             the retrieval gate abstained; no generator call made
# insufficient_context  the gate passed but the model found no answer in the context
Status = Literal["answered", "abstained", "insufficient_context"]

DISCLAIMER = ("GetRight gives legal information, not legal advice. Check the cited provisions, "
              "and contact the Department of Labour or a lawyer about your own situation.")


class Citation(BaseModel):
    number: int
    chunk_id: str
    citation: str
    statute: str
    act_number: str | None = None
    section: str | None = None
    subsection: str | None = None
    section_title: str | None = None
    jurisdiction: str
    status: str
    source_page: int | None = None
    source_url: str | None = None
    source_version: str | None = None

    @classmethod
    def from_chunk(cls, number: int, chunk: RetrievedChunk) -> "Citation":
        fields = {name: getattr(chunk, name) for name in cls.model_fields if name != "number"}
        return cls(number=number, **fields)


class Abstention(BaseModel):
    reason: AbstainReason
    statutes_held: list[str]
    message: str


class AnswerChecks(BaseModel):
    """Traceability checks on the generated text, for evaluation."""
    invalid_markers: list[int] = []      # markers with no matching context block, removed from the text
    uncited_sentences: int = 0           # sentences of 6+ words with no marker
    provision_mentions: list[str] = []   # Acts or sections named in the prose (the prompt forbids it)
    # Cited chunks that are not current law: deleted, omitted or not yet in force,
    # or superseded and cited without the amending chunk.
    non_current_citations: list[str] = []
    truncated: bool = False              # the model stopped at max_tokens


class GeneratorInfo(BaseModel):
    model: str
    temperature: float
    seed: int | None
    prompt_version: str
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class GeneratedAnswer(BaseModel):
    query: str
    region: str | None
    status: Status
    answer: str | None
    citations: list[Citation]
    abstention: Abstention | None
    notes: list[str]
    external_dependencies: list[str]
    checks: AnswerChecks
    generator: GeneratorInfo | None      # null when no call was made
    context_chunk_ids: list[str]
    index_version: str
    disclaimer: str = DISCLAIMER

    @model_validator(mode="after")
    def _consistent(self) -> "GeneratedAnswer":
        if self.status == "answered" and not self.answer:
            raise ValueError("an answered result needs answer text")
        if self.status == "abstained":
            if self.abstention is None:
                raise ValueError("an abstained result needs an abstention notice")
            if self.answer is not None or self.citations:
                raise ValueError("an abstained result has no answer and no citations")
        numbers = [c.number for c in self.citations]
        if numbers != list(range(1, len(numbers) + 1)):
            raise ValueError(f"citation numbers must be 1..n in order, got {numbers}")
        return self
