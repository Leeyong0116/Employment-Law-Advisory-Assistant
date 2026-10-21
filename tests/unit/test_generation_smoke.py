"""Tests for the helpers in src/generation/smoke.py (the live run itself needs the server)."""
from src.generation.schema import AnswerChecks, Citation, GeneratedAnswer
from src.generation.smoke import CHECKS, cites, leaked, territories


def _cit(number, chunk_id, jurisdiction):
    return Citation(number=number, chunk_id=chunk_id, citation=chunk_id, statute="S", jurisdiction=jurisdiction,
                    status="in_force")


def _answer(*citations):
    return GeneratedAnswer(query="q", region=None, status="answered", answer="a [1].", citations=list(citations),
                           abstention=None, notes=[], external_dependencies=[], checks=AnswerChecks(), generator=None,
                           context_chunk_ids=[c.chunk_id for c in citations], index_version="v")


def test_cites_matches_prefix_on_id_boundary():
    answer = _answer(_cit(1, "EA1955_s60A_3_def_overtime", "Peninsular Malaysia and Labuan"))
    assert cites(answer, "EA1955_s60A_3")
    assert not cites(answer, "EA1955_s60A_30")
    assert not cites(answer, "EA1955_s60")


def test_territories_ignore_nationwide():
    answer = _answer(_cit(1, "SBH67_s83_1", "Sabah"), _cit(2, "IRA1967_s20_1", "Malaysia"), _cit(3, "SBH67_s84_1", "Sabah"))
    assert territories(answer) == {"Sabah"}


def test_leaked_lists_citations_outside_the_region():
    answer = _answer(_cit(1, "SBH67_s83_1", "Sabah"), _cit(2, "EA1955_s60E_1", "Peninsular Malaysia and Labuan"))
    assert leaked(answer, ["Sabah", "Malaysia"]) == ["EA1955_s60E_1"]
    assert leaked(answer, None) == []


def test_seven_checks_with_reasons():
    assert len(CHECKS) == 7
    assert all(check.why for check in CHECKS)
