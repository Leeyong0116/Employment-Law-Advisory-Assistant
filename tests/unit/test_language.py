"""Tests for src/retrieval/language.py, with the real lingua detector (deterministic)."""
import pytest

pytest.importorskip("lingua")

from src.retrieval.language import LanguageGate  # noqa: E402


@pytest.fixture(scope="module")
def gate():
    return LanguageGate(min_words=3, min_english_share=0.3)


@pytest.mark.parametrize("query", [
    "How many days of annual leave am I entitled to?",
    "my boss fired me without telling me",
    "can my employer cut my salary",
    "can I bring my dog to work",
    "Is the housing rule in force in Sabah?",
    "Do part-time employees get public holidays?",
])
def test_english_passes(gate, query):
    check = gate.check(query)
    assert check.passed and check.language == "en"


@pytest.mark.parametrize("query", [
    "Can I claim cuti sakit?",
    "My boss tak bayar gaji, what can I do?",
    "How many days cuti bersalin for Sabah?",
    "Can my majikan terminate me without notice?",
    "Boleh I claim cuti sakit?",
    "Is it legal for my employer to deduct gaji?",
])
def test_mixed_english_and_malay_passes(gate, query):
    assert gate.check(query).passed


@pytest.mark.parametrize("query", [
    "cuti bersalin berapa hari",
    "Berapa hari cuti tahunan saya?",
    "Majikan saya tidak membayar gaji",
    "Adakah majikan boleh potong gaji saya?",
    "boss saya pecat saya tanpa notis",
    "Saya kena buang kerja tanpa notis",
])
def test_malay_is_stopped(gate, query):
    check = gate.check(query)
    assert not check.passed and check.language in ("ms", "id")


@pytest.mark.parametrize("query, language", [
    ("产假有几天", "zh"),
    ("我的老板不付工资怎么办", "zh"),
    ("எனக்கு எத்தனை நாள் விடுப்பு?", "ta"),
])
def test_other_scripts_are_stopped_even_when_short(gate, query, language):
    check = gate.check(query)
    assert not check.passed and check.language == language


@pytest.mark.parametrize("query", ["EPF", "section 60E", "nihao", "overtime rate", "60E", "?"])
def test_short_queries_pass_without_a_verdict(gate, query):
    check = gate.check(query)
    assert check.passed and check.language is None


def test_mixed_query_is_labelled_mixed(gate):
    assert gate.check("Can I claim cuti sakit?").language == "mixed"
