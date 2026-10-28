"""Typed request and response models for the M5 API.

Answer and citations stay separate typed fields. Provision is the full text of
one cited chunk for the source panel; it is copied from chunk metadata and
exposes none of the parser's internal fields (parse_rule, row_id, doc_id...).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Region = Literal["peninsular", "sabah", "sarawak"]

MAX_QUERY_CHARS = 2000


class AskRequest(BaseModel):
    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    region: Region | None = None

    @field_validator("query", mode="before")
    @classmethod
    def _strip(cls, value):
        return value.strip() if isinstance(value, str) else value


class ApiError(BaseModel):
    code: str
    message: str


class Meta(BaseModel):
    """What the abstention notice and the Help page need: statutes and territories."""
    statutes_held: list[str]
    regions: dict[str, list[str]]        # region -> jurisdictions whose law applies there
    disclaimer: str
    index_version: str
    prompt_version: str
    model: str


_LIST_FIELDS = (
    "cross_references_internal",
    "cross_references_external",
    "in_force_notes",
    "amended_by",
    "amends",
    "section_chunk_ids",
)


class Provision(BaseModel):
    chunk_id: str
    citation: str
    statute: str
    act_number: str | None = None
    part: str | None = None
    part_title: str | None = None
    section: str | None = None
    section_title: str | None = None
    subsection: str | None = None
    chunk_type: str
    jurisdiction: str
    status: str
    deleted_by: str | None = None
    content: str
    source_version: str | None = None
    source_page: int | None = None
    source_page_end: int | None = None
    source_url: str | None = None
    cross_references_internal: list[str] = []
    cross_references_external: list[str] = []
    in_force_notes: list[str] = []
    amended_by: list[str] = []
    amends: list[str] = []
    # Every chunk of the same section, in order, so the panel can show the
    # whole section around the cited subsection.
    section_chunk_ids: list[str] = []

    @field_validator(*_LIST_FIELDS, mode="before")
    @classmethod
    def _none_is_empty(cls, value):
        return [] if value is None else value

    @classmethod
    def from_chunk(cls, chunk: dict, section_chunk_ids: list[str]) -> "Provision":
        known = {name: chunk[name] for name in cls.model_fields if name in chunk and name != "section_chunk_ids"}
        return cls(**known, section_chunk_ids=section_chunk_ids)
