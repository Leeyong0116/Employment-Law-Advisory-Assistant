"""Tests for src/evaluation/rewrite.py."""
import pytest
from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from src.evaluation.rewrite import REWRITE_PROMPT, REWRITE_RULES, added_numbers, clean_rewrite, malay_variants, rewrite_query

AUTHOR_PROMPT = ("Rewrite the user's question into formal Malaysian employment-law terms\n"
                 "for searching statutes. Fix spelling. Translate Malay/Manglish words.\n"
                 "Do NOT answer the question. Do NOT add facts, numbers, or legal\n"
                 "conclusions that the user did not state. Output one sentence only.")


class RecordingFake(GenericFakeChatModel):
    seen: list = []

    def _generate(self, messages, *args, **kwargs):
        self.seen.append(messages)
        return super()._generate(messages, *args, **kwargs)


# The author's prompt alone made Qwen3 answer in Malay for 82 of 97 questions ("Malaysian" read as
# Bahasa Malaysia), against the agreed design (translate to English). One sentence is added.
ENGLISH_LINE = "\nWrite the rewritten question in English."


def test_rules_are_the_authors_prompt_plus_english():
    assert REWRITE_RULES == AUTHOR_PROMPT + ENGLISH_LINE


def test_clean_strips_label_quotes_and_extra_lines():
    raw = 'Rewritten question: "What are the employer\'s obligations when wages are not paid?"\nNote: spelling fixed.'
    assert clean_rewrite(raw) == "What are the employer's obligations when wages are not paid?"


@pytest.mark.parametrize("raw", ["Formal question: When must wages be paid?", "  'When must wages be paid?'  ",
                                 "\n\nQuery: When must wages be paid?"])
def test_clean_other_wrappers(raw):
    assert clean_rewrite(raw) == "When must wages be paid?"


def test_clean_empty_raises():
    with pytest.raises(ValueError):
        clean_rewrite('  ""  \n')


def test_added_numbers_flags_new_numbers():
    assert added_numbers("what if my boss havent paid me after 30 working days",
                         "Must wages be paid within seven days, and what if they are unpaid after 30 days?") == ["seven"]


def test_added_numbers_empty_when_faithful():
    assert added_numbers("cuti bersalin berapa hari", "How many days of maternity leave is an employee entitled to?") == []


def test_rewrite_query_uses_the_question():
    model = RecordingFake(messages=iter([AIMessage(content='Rewritten question: "When must an employer pay wages?"')]))
    model.seen = []
    assert rewrite_query(REWRITE_PROMPT | model, "boss never pay me") == "When must an employer pay wages?"
    system, human = model.seen[0]
    assert system.content == AUTHOR_PROMPT + ENGLISH_LINE and human.content == "boss never pay me"


def test_malay_variants_from_csv(tmp_path):
    csv_path = tmp_path / "faq.csv"
    csv_path.write_text("﻿id,question_en,question_ms\n"
                        "JTKSM-05,Does this apply?,Adakah pindaan ini terpakai di seluruh Malaysia?\n"
                        "JTKSM-06,Other?,\n", encoding="utf-8")
    gold = [{"id": "JTKSM-05", "question": "Does this apply?", "region": "peninsular", "in_scope": True,
             "scope_class": "in_scope", "expected_chunk_ids": ["EA1955_s1_2"]},
            {"id": "JTKSM-06", "question": "Other?", "region": None, "in_scope": True, "scope_class": "in_scope",
             "expected_chunk_ids": []}]
    variants = malay_variants(gold, csv_path)
    assert len(variants) == 1
    v = variants[0]
    assert (v["id"], v["parent"], v["question"]) == ("JTKSM-05-ms", "JTKSM-05", "Adakah pindaan ini terpakai di seluruh Malaysia?")
    assert (v["region"], v["expected_chunk_ids"], v["scope_class"]) == ("peninsular", ["EA1955_s1_2"], "in_scope")
