"""The prompt (M4): numbered context blocks plus fixed rules.

Each retrieved chunk becomes one block, numbered in RetrievalResult order
(ranked chunks first, then expansion). The block header is built from chunk
metadata only. The model cites by block number; src/generation/citations.py
turns the numbers back into citations from the same metadata, so the model
never writes a citation itself (CLAUDE.md, core contribution 1).

The rules ask the model to answer only from the blocks. Whether it did is
measured afterwards (faithfulness); nothing here checks that a provision
legally supports the answer (CLAUDE.md, core contribution 2).
"""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel

from src.retrieval.schema import RetrievalResult, RetrievedChunk

PROMPT_VERSION = "m4-v2"  # v2: rule 5, non-current sources (review of 2026-10-21)
INSUFFICIENT = "INSUFFICIENT_CONTEXT"

REGION_NAMES = {"peninsular": "Peninsular Malaysia or Labuan", "sabah": "Sabah", "sarawak": "Sarawak"}
STATUS_LABELS = {"in_force": "in force", "deleted": "DELETED", "omitted": "OMITTED",
                 "not_yet_in_force": "NOT YET IN FORCE"}

SYSTEM_RULES = f"""You explain Malaysian employment law using only the numbered sources given to you.

Rules:
1. Answer only from the numbered sources. If they do not answer the question, reply exactly {INSUFFICIENT} and nothing else.
2. After each sentence that states the law, add the marker of the source(s) it comes from, like [1] or [2][3].
3. Refer to sources only by their marker. Do not name Acts, Ordinances or section numbers yourself.
4. Where a source is marked SUPERSEDED, state the amended rule from the amending source, not the old wording.
5. A source marked DELETED, OMITTED or NOT YET IN FORCE is not current law. Do not state it as the current rule; if you mention it, say that it is deleted or not yet in force.
6. Explain in plain language what the law says. Do not tell the user what they should do, and do not give legal advice.
7. If the sources come from more than one territory, say which rule applies in which territory."""

USER_TEMPLATE = """User's region: {region}

{notes}Sources:

{context}

Question: {question}"""

PROMPT = ChatPromptTemplate.from_messages([("system", SYSTEM_RULES), ("human", USER_TEMPLATE)])


class Prompt(BaseModel):
    variables: dict[str, str]      # inputs for PROMPT
    blocks: list[RetrievedChunk]   # block n is blocks[n - 1]
    notes: list[str]


def _status_label(chunk: RetrievedChunk, position: dict[str, int]) -> str:
    if chunk.status != "superseded":
        return STATUS_LABELS.get(chunk.status, chunk.status)
    shown = [position[a] for a in chunk.amended_by if a in position]
    where = ("see block " + ", ".join(map(str, shown))) if shown else "amending text not shown"
    return f"SUPERSEDED, amended by {', '.join(chunk.amended_by)} ({where})"


def _block(number: int, chunk: RetrievedChunk, position: dict[str, int]) -> str:
    header = [f"[{number}] {chunk.citation}"]
    if chunk.section_title:
        header.append(chunk.section_title)
    header += [chunk.jurisdiction, _status_label(chunk, position)]
    return "\n".join([" | ".join(header), chunk.content, *chunk.in_force_notes])


def _jurisdiction_key(label: str) -> str:
    return label.lower().replace(" ", "_")


def build_prompt(result: RetrievalResult, jurisdiction_notes: dict) -> Prompt:
    """Template inputs and numbered blocks for one answerable RetrievalResult."""
    if result.abstained:
        raise ValueError("retrieval abstained: there is nothing to build a prompt from")
    blocks = list(result.chunks)
    position = {chunk.chunk_id: n for n, chunk in enumerate(blocks, start=1)}
    present = {_jurisdiction_key(chunk.jurisdiction) for chunk in blocks}
    notes = [entry["note"].strip() for key, entries in jurisdiction_notes.items() if key in present for entry in entries]
    variables = {
        "region": REGION_NAMES.get(result.region, result.region) if result.region else "not given",
        "notes": "".join(f"Note: {note}\n\n" for note in notes),
        "context": "\n\n".join(_block(n, chunk, position) for n, chunk in enumerate(blocks, start=1)),
        "question": result.query,
    }
    return Prompt(variables=variables, blocks=blocks, notes=notes)
