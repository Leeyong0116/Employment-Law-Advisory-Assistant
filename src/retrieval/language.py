"""Language gate: stop non-English questions before retrieval.

The corpus is English and BM25 has no word overlap with, say, a Malay
question, while the dense side still returns its nearest (wrong) chunks.
So a non-English question gets a "please ask in English" notice instead of
an answer built from junk (CLAUDE.md; Bahasa Malaysia is future work).

Malaysians often mix English and Malay ("Can I claim cuti sakit?"). That
must pass. Whole-text detection fails here: lingua gives that question an
English confidence of 0.16, close to pure Malay (0.00 to 0.02). So the gate
counts words instead: a word is English if it is an English function word
or lingua scores it English on its own (function words alone are too
short to detect). The question passes if at least `min_english_share` of
its words are English. Measured on 27 questions (2026-10-10): English and
mixed questions 0.4 and above, Malay ones 0.17 and below.

Rules, in order:
1. Mostly non-Latin letters (Chinese, Tamil): stopped, at any length.
2. Fewer than `min_words` words: passes with no verdict ("EPF", "section
   60E"); detection on so little text is unreliable, and nonsense such as
   "nihao" is left to the reranker gate.
3. English share below `min_english_share`: stopped.

lingua is restricted to the languages a Malaysian user is likely to type;
the detector is deterministic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_WORD = re.compile(r"[^\W\d_]+")
_FUNCTION_WORDS = frozenset("""
a an the i me my mine we us our you your he him his she her it its they them their
is am are was were be been being do does did done have has had can could will would shall should
may might must not no yes of in on at to for from by with without about as if or and but so than
then there here what which who whom whose when where why how many much any some all this that
these those up out over under after before again also just only very too
""".split())
_WORD_CONFIDENCE = 0.5


@dataclass(frozen=True)
class LanguageCheck:
    passed: bool
    language: str | None  # "en", "mixed", an ISO 639-1 code, or None (too short to tell)


def _is_latin(char: str) -> bool:
    return ord(char) < 0x250  # Basic Latin to Latin Extended-B


class LanguageGate:
    def __init__(self, min_words: int = 3, min_english_share: float = 0.3):
        from lingua import Language, LanguageDetectorBuilder

        self.min_words, self.min_english_share = min_words, min_english_share
        self._english = Language.ENGLISH
        self._detector = LanguageDetectorBuilder.from_languages(
            Language.ENGLISH, Language.MALAY, Language.INDONESIAN, Language.CHINESE, Language.TAMIL,
        ).build()

    def _code(self, text: str) -> str | None:
        language = self._detector.detect_language_of(text)
        return None if language is None else language.iso_code_639_1.name.lower()

    def _is_english(self, word: str) -> bool:
        return (word.lower() in _FUNCTION_WORDS
                or self._detector.compute_language_confidence(word, self._english) >= _WORD_CONFIDENCE)

    def check(self, query: str) -> LanguageCheck:
        letters = [char for char in query if char.isalpha()]
        if letters and sum(not _is_latin(char) for char in letters) > len(letters) / 2:
            return LanguageCheck(False, self._code(query))
        words = _WORD.findall(query)
        if len(words) < self.min_words:
            return LanguageCheck(True, None)
        share = sum(map(self._is_english, words)) / len(words)
        if share < self.min_english_share:
            return LanguageCheck(False, self._code(query))
        return LanguageCheck(True, "en" if self._code(query) == "en" else "mixed")
