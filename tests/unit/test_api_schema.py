from pathlib import Path
from typing import get_args

import pytest
import yaml
from pydantic import ValidationError

from src.api.schema import AskRequest, Provision, Region

CHUNK = {
    "chunk_id": "EA1955_s59_1",
    "statute": "Employment Act 1955",
    "act_number": "Act 265",
    "part": "Part XII",
    "part_title": "Rest Day, Hours of Work, Holidays and Other Conditions of Service",
    "section": "59",
    "section_title": "Rest day",
    "subsection": "(1)",
    "citation": "Employment Act 1955, s. 59(1)",
    "chunk_type": "provision",
    "content": "Every employee shall be allowed one rest day in each week.",
    "status": "in_force",
    "deleted_by": None,
    "source_page_end": 54,
    "jurisdiction": "Peninsular Malaysia and Labuan",
    "source_version": "as at 1 January 2023",
    "source_page": 53,
    "source_url": "https://lom.agc.gov.my/",
    "cross_references_internal": ["s. 37"],
    "cross_references_external": [],
    "in_force_notes": [],
    "amended_by": [],
    "amends": [],
    "parse_rule": "subsection",
    "row_id": None,
}


def test_query_is_stripped():
    assert AskRequest(query="  rest day?  ").query == "rest day?"


def test_blank_query_rejected():
    with pytest.raises(ValidationError):
        AskRequest(query="   ")


def test_long_query_rejected():
    with pytest.raises(ValidationError):
        AskRequest(query="a" * 2001)


def test_query_at_limit_accepted():
    assert len(AskRequest(query="a" * 2000).query) == 2000


def test_unknown_region_rejected():
    with pytest.raises(ValidationError):
        AskRequest(query="q", region="labuan")


def test_region_matches_config():
    config = yaml.safe_load(Path("config/config.yaml").read_text(encoding="utf-8"))
    assert set(get_args(Region)) == set(config["retrieval"]["regions"])


def test_provision_from_chunk():
    p = Provision.from_chunk(CHUNK, ["EA1955_s59_1", "EA1955_s59_2"])
    assert p.chunk_id == CHUNK["chunk_id"]
    assert p.section_chunk_ids == ["EA1955_s59_1", "EA1955_s59_2"]
    assert p.source_page_end == 54 and p.deleted_by is None
    assert not hasattr(p, "parse_rule")
    assert not hasattr(p, "row_id")


def test_provision_list_fields_accept_none():
    p = Provision.from_chunk({**CHUNK, "amended_by": None, "in_force_notes": None}, [])
    assert p.amended_by == [] and p.in_force_notes == []
