"""Tests for src/ingestion/extract.py.

Fixture strings are copied from real PyMuPDF output over data/raw, not
invented — see the docstrings for which document and page each came from.
"""
import pathlib

import pytest

from src.ingestion import extract


class TestNormaliseGlyphs:
    def test_private_use_footnote_rule_is_recognised(self):
        # IRA p.40 separates its footnotes with a run of \uf0be (Symbol font).
        assert extract.normalise_glyphs("\uf0be" * 28) == "\u2014" * 28

    def test_mangled_note_dash_becomes_an_em_dash(self):
        # IRA p.40 extracts as "*NOTE\ufffd The proviso inserted ..."
        assert extract.normalise_glyphs("*NOTE\ufffd The proviso") == "*NOTE\u2014 The proviso"

    def test_ordinary_text_is_untouched(self):
        assert extract.normalise_glyphs("Every employee shall") == "Every employee shall"


class TestDigitSignature:
    def test_page_numbers_are_masked_so_furniture_repeats(self):
        a = extract.digit_signature("42    Laws of Malaysia    ACT 265")
        b = extract.digit_signature("64    Laws of Malaysia    ACT 265")
        assert a == b

    def test_different_furniture_keeps_distinct_signatures(self):
        assert extract.digit_signature("Employment  41") != extract.digit_signature(
            "Industrial Relations  41"
        )


class TestFindFurnitureSignatures:
    def test_a_line_repeating_across_pages_is_furniture(self):
        pages = [["FOR REFERENCE ONLY (JUNE 2026)", str(n), "body text here"] for n in range(40, 50)]
        found = extract.find_furniture_signatures(pages)
        assert extract.digit_signature("FOR REFERENCE ONLY (JUNE 2026)") in found

    def test_body_text_is_never_furniture(self):
        bodies = [
            "Every employee shall be allowed a rest day",
            "the maternity allowance shall be paid",
            "no employer shall terminate the contract",
            "the Director General may inquire into",
            "wages shall be paid before the seventh day",
        ]
        pages = [
            ["FOR REFERENCE ONLY (JUNE 2026)", str(40 + n), body]
            for n, body in enumerate(bodies)
        ]
        found = extract.find_furniture_signatures(pages)
        for body in bodies:
            assert extract.digit_signature(body) not in found

    def test_a_repeated_body_line_at_no_fixed_position_is_not_furniture(self):
        # Sabah has 142 lines reading "Section N. [Deleted by AAnnnn]", which
        # share a digit signature. Frequency alone would strip them as
        # furniture and silently delete every repealed section from the corpus.
        # What saves them is position: they drift through the body rather than
        # sitting in a fixed slot at a page edge.
        pages = []
        for n in range(40, 60):
            body = ["body"] * (n % 4 + 3)
            body.insert(n % 3 + 1, f"Section {n}. [Deleted by AA1238]")
            pages.append(["FOR REFERENCE ONLY (JUNE 2026)", str(n), *body, "closing line"])
        found = extract.find_furniture_signatures(pages)
        assert extract.digit_signature("Section 41. [Deleted by AA1238]") not in found

    def test_recto_verso_alternation_is_still_detected(self):
        # The EA alternates: odd pages "Employment"/"41", even pages
        # "42  Laws of Malaysia  ACT 265". Each appears on only half the pages.
        pages = []
        for n in range(40, 60):
            if n % 2:
                pages.append(["Employment", str(n), "body"])
            else:
                pages.append([f"{n}    Laws of Malaysia    ACT 265", "body"])
        found = extract.find_furniture_signatures(pages)
        assert extract.digit_signature("Employment") in found
        assert extract.digit_signature("42    Laws of Malaysia    ACT 265") in found


class TestPrintedPageNumber:
    def test_number_on_its_own_line(self):
        assert extract.printed_page_number(["FOR REFERENCE ONLY (JUNE 2026)", "41"]) == 41

    def test_number_embedded_in_a_header(self):
        assert extract.printed_page_number(["42   Laws of Malaysia   ACT 265"]) == 42

    def test_number_at_the_end_of_a_header(self):
        assert extract.printed_page_number(["Industrial Relations      41"]) == 41

    def test_absent_number_is_none_not_a_guess(self):
        # A citation must never carry an invented page.
        assert extract.printed_page_number(["Sarawak Lawnet", "LABOUR"]) is None


class TestSplitFootnotes:
    def test_footnote_after_the_rule_is_lifted_out_of_the_body(self):
        lines = [
            "whose decision thereon shall be final.",
            "\u2014" * 28,
            "*NOTE\u2014 The proviso inserted is not yet in force \u2014 see section 18 of the Act A1615.",
        ]
        body, notes = extract.split_footnotes(lines)
        assert body == ["whose decision thereon shall be final."]
        assert len(notes) == 1
        assert notes[0].startswith("*NOTE")

    def test_body_without_a_rule_is_returned_whole(self):
        lines = ["Every employee shall be allowed in each week a rest day"]
        body, notes = extract.split_footnotes(lines)
        assert body == lines
        assert notes == []


class TestRejoinLetterSpaced:
    def test_word_boundaries_come_from_gaps_not_spaces(self):
        # A1754 p.26: "(a) h e h a s b e e n e m p l o y e d b y", where the
        # intra-word gap is 1.93pt and the inter-word gap is 12.43pt.
        tokens = list("hehasbeenemployedby")
        gaps = []
        for word_len in (2, 3, 4, 8, 2):
            gaps.extend([1.93] * (word_len - 1))
            gaps.append(12.43)
        gaps.pop()
        assert extract.rejoin_letter_spaced(tokens, gaps) == "he has been employed by"

    def test_a_single_word_run_has_no_breaks(self):
        assert extract.rejoin_letter_spaced(list("definition"), [1.93] * 9) == "definition"


def _pages_for(filename):
    path = pathlib.Path("data/raw") / filename
    if not path.exists():
        pytest.skip("source PDFs not present")
    return extract.extract_pages(path)


@pytest.fixture(scope="module")
def ea_pages():
    return _pages_for("Akta Kerja 1955 (Akta 265).pdf")


@pytest.fixture(scope="module")
def sabah_pages():
    return _pages_for("Labour Ordinance (Sabah Cap. 67).pdf")


@pytest.fixture(scope="module")
def ira_pages():
    return _pages_for("INDUSTRIAL RELATION.pdf")


@pytest.mark.corpus
class TestAgainstTheRealCorpus:
    def test_every_page_is_returned(self, ea_pages):
        assert len(ea_pages) == 127

    def test_printed_page_number_is_read_not_computed(self, ea_pages):
        # PDF index 40 carries printed page 41 in the EA.
        assert ea_pages[40].printed_page == 41

    def test_running_header_is_stripped_from_the_body(self, ea_pages):
        assert "Laws of Malaysia" not in ea_pages[41].text
        assert "findings in respect thereof" in ea_pages[41].text

    def test_a_proviso_is_not_split_by_page_furniture(self, ea_pages):
        # s.60E's proviso runs across the page break at printed p.63/64; the
        # header that lands mid-sentence must be gone from the body text.
        joined = "\n".join(p.text for p in ea_pages)
        assert "his entitlement to such leave accrues" in joined
        assert "Laws of Malaysia  ACT 265" not in joined

    def test_no_repealed_section_is_lost_to_furniture_stripping(self, sabah_pages):
        # 142 "[Deleted by ...]" markers in Sabah Cap. 67. They share a digit
        # signature with each other, so a frequency-only furniture rule would
        # strip them and quietly erase every repealed section from the corpus.
        kept = sum(p.text.count("[Deleted by") for p in sabah_pages)
        assert kept == 142

    def test_every_sabah_page_yields_a_printed_page_number(self, sabah_pages):
        assert all(p.printed_page is not None for p in sabah_pages)

    def test_editorial_footnotes_are_lifted_out_of_the_body(self, ira_pages):
        # The IRA carries its not-yet-in-force annotations as "*NOTE--"
        # footnotes below a Symbol-font rule. They are AGC commentary, not
        # statute, so serving them as content would be a faithfulness failure.
        notes = [n for p in ira_pages for n in p.footnotes]
        assert any("not yet in force" in n for n in notes)
        assert not any("*NOTE" in p.text for p in ira_pages)

    def test_letter_spaced_lines_are_rejoined_into_words(self):
        pages = _pages_for("Sarawak amendment.pdf")
        joined = "\n".join(p.text for p in pages)
        assert "he has been employed by" in joined
        assert "h e h a s b e e n" not in joined

    def test_the_sarawak_watermark_is_removed(self):
        pages = _pages_for("sarawak ordinance.pdf")
        joined = "\n".join(p.text for p in pages)
        assert "Sarawak Lawnet" not in joined
        assert "For Reference Only" not in joined

    def test_a_three_line_header_still_yields_its_page_number(self):
        # Sarawak Cap. 76 runs "Sarawak Lawnet" / "LABOUR" / "39", putting the
        # number one line beyond the furniture window.
        pages = _pages_for("sarawak ordinance.pdf")
        assert pages[40].printed_page == 39
        numbered = sum(p.printed_page is not None for p in pages)
        assert numbered >= 110, f"only {numbered}/{len(pages)} pages carry a page number"

    def test_subsection_markers_survive_the_wider_page_number_window(self):
        # "(2)" and "(c)" sit at the same position as Cap. 76's page number.
        # Claiming that position for anything but a bare numeral would destroy
        # the subsection numbering the whole citation scheme depends on.
        pages = _pages_for("sarawak ordinance.pdf")
        joined = "\n".join(p.text for p in pages)
        assert "(2)" in joined and "(c)" in joined

    def test_ea_footnotes_are_lifted_even_without_a_rule(self, ea_pages):
        # The EA draws no Symbol-font rule; it just starts a line with "*NOTE".
        notes = [n for p in ea_pages for n in p.footnotes]
        assert len(notes) == 14
        assert not any("NOTE" in p.text for p in ea_pages)

    def test_a_wrapped_footnote_is_folded_into_one_note(self, ea_pages):
        notes = [n for p in ea_pages for n in p.footnotes]
        extended = next(n for n in notes if "Federal Territory of Labuan" in n)
        assert extended.endswith("w.e.f. 1 November 2000.")

    def test_two_notes_on_one_page_stay_separate(self, ea_pages):
        # Printed p.81 carries both a "*NOTE" and a "**NOTE".
        page = next(p for p in ea_pages if p.printed_page == 81)
        assert len(page.footnotes) == 2
