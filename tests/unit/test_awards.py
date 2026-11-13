"""Tests for src/ingestion/awards.py (A1), on synthetic page text: no PDFs."""
from src.ingestion.awards import (
    award_chunks,
    clean_pages,
    join_lines,
    split_paragraphs,
    statutes_applied,
    validate_award,
)

META = {
    "file": "Award_1806-2025_Test.pdf", "award_number": "1806 of 2025", "case_number": "10/4-1123/24",
    "case_name": "A binti B v C Sdn. Bhd.", "award_date": "2025-11-25", "chairman": "D bin E",
    "venue": "Ipoh, Perak", "numbering": "bracket", "reasoning_from": 2,
}

PAGES = [
    ["1", "IN THE INDUSTRIAL COURT OF MALAYSIA", "CASE NO. 10/4-1123/24", "AWARD NO. 1806 OF 2025", " ",
     "[1]", "The Claimant was employed on 1 May.", " ", "[2]", "The burden is on the Company to prove the mis-"],
    ["2", "conduct on a balance of probabilities. The Court finds:", " ", "“(3) a quoted list item", "(4) another”", " ",
     "[3]", "The dismissal was without just cause or excuse under the Industrial", "Relations Act 1967 and the",
     "Employment Act 1955.", " ", "HANDED DOWN AND DATED THIS 25th DAY OF NOVEMBER 2025", "Signed", "CHAIRMAN"],
]


def test_page_numbers_at_the_edges_are_dropped_but_not_other_numbers():
    pages = clean_pages([["3", "text", "12 months", "4"], ["  5 ", "more"]])
    assert pages == [["text", "12 months"], ["more"]]


def test_lines_join_into_running_text_with_hyphens_and_breaks():
    # A line-end hyphen is a real hyphen: the awards are typeset from Word, which does not hyphenate words.
    assert join_lines(["survival post-", "termination was", "proven.", " ", "Next point."]) == "survival post-termination was proven.\nNext point."
    assert join_lines(["berturut-", "turut"]) == "berturut-turut"
    assert join_lines(["The", "parties", "to", "the", "dispute"]) == "The parties to the dispute"
    assert join_lines(["Kuala Lumpur-", "Selangor"]) == "Kuala Lumpur-Selangor"  # capital after hyphen: keep it


def test_paragraphs_follow_the_number_sequence_and_stop_at_the_signature():
    paragraphs = split_paragraphs(clean_pages(PAGES), "bracket")
    assert [p.number for p in paragraphs] == [1, 2, 3]
    assert paragraphs[1].text.startswith("The burden is on the Company to prove the mis-conduct on a balance")
    assert "(3) a quoted list item" in paragraphs[1].text  # a quoted list does not split a paragraph
    assert (paragraphs[1].page, paragraphs[1].page_end) == (1, 2)
    assert "HANDED DOWN" not in paragraphs[2].text and "CHAIRMAN" not in paragraphs[2].text


def test_other_numbering_styles():
    dot = split_paragraphs([["1. First point.", "2. Second point.", "3. Third."]], "dot")
    paren = split_paragraphs([["(1) First.", "(2) Second."]], "paren")
    assert [p.text for p in dot] == ["First point.", "Second point.", "Third."]
    assert [p.number for p in paren] == [1, 2]


def test_a_number_out_of_sequence_is_text_not_a_new_paragraph():
    paragraphs = split_paragraphs([["[1] One.", "[5] cited as in another award", "[2] Two."]], "bracket")
    assert [p.number for p in paragraphs] == [1, 2]
    assert paragraphs[0].text == "One. [5] cited as in another award"


def test_statutes_named_in_the_award():
    text = "under section 20(3) of the Industrial Relations Act 1967 ... section 14 of the Employment Act 1955 ... Sabah Labour Ordinance"
    assert statutes_applied(text) == ["Industrial Relations Act 1967", "Employment Act 1955", "Labour Ordinance (Sabah)"]


def test_chunks_keep_the_reasoning_only_with_citation_fields():
    paragraphs = split_paragraphs(clean_pages(PAGES), "bracket")
    chunks = award_chunks(META, paragraphs, ["Industrial Relations Act 1967"])
    assert [c["chunk_id"] for c in chunks] == ["ICA2025_1806_p2", "ICA2025_1806_p3"]
    first = chunks[0]
    assert first["citation"] == "Award No. 1806 of 2025, para 2"
    assert first["doc_id"] == "ICA2025_1806" and first["doc_type"] == "award" and first["chunk_type"] == "award_paragraph"
    assert first["jurisdiction"] == "Malaysia" and first["source_page"] == 1 and first["source_page_end"] == 2
    assert first["case_name"] == "A binti B v C Sdn. Bhd." and first["paragraph"] == 2
    assert first["statutes_applied"] == ["Industrial Relations Act 1967"]
    assert first["source_version"] == "handed down 25 November 2025"


def test_validation_passes_a_clean_award():
    text = "\n".join(line for page in PAGES for line in page)
    paragraphs = split_paragraphs(clean_pages(PAGES), "bracket")
    assert validate_award({**META, "reasoning_from": 2, "min_reasoning": 2}, paragraphs, text) == []


def test_validation_catches_a_wrong_award_number_a_gap_and_a_bad_start():
    text = "\n".join(line for page in PAGES for line in page)
    paragraphs = split_paragraphs(clean_pages(PAGES), "bracket")
    problems = validate_award({**META, "award_number": "999 of 2025", "reasoning_from": 7, "min_reasoning": 2},
                              paragraphs[:1] + paragraphs[2:], text)
    assert any("award number 999 of 2025 not found" in p for p in problems)
    assert any("paragraphs not consecutive" in p for p in problems)
    assert any("reasoning_from 7" in p for p in problems)


def test_running_headers_and_page_of_lines_are_dropped_but_not_paragraph_markers():
    pages = [["19/4-491/22", "1", "[1] One."], ["19/4-491/22", "2", "[2] Two.", "Page 2 of 3"],
             ["19/4-491/22", "3", "[3] Three."]]
    assert clean_pages(pages) == [["[1] One."], ["[2] Two."], ["[3] Three."]]


def test_a_dot_marker_alone_on_its_line():
    paragraphs = split_paragraphs([["1.", "First point.", "2.", "Second point."]], "dot")
    assert [(p.number, p.text) for p in paragraphs] == [(1, "First point."), (2, "Second point.")]


def test_declared_skips_follow_the_published_numbering():
    pages = [["[1] One.", "[3] Three.", "[4] Four."]]
    assert [p.number for p in split_paragraphs(pages, "bracket", skips=[2])] == [1, 3, 4]
    assert [p.number for p in split_paragraphs(pages, "bracket")] == [1]  # undeclared gap: the sequence stops


def test_validation_accepts_declared_skips_and_reports_where_an_undeclared_one_stops():
    text = "AWARD NO. 1806 OF 2025\nCASE NO. 10/4-1123/24\n[1] a\n[3] b\n[4] c\n[5] d\n[6] e\n[7] f\n[8] g"
    pages = [["[1] a", "[3] b", "[4] c", "[5] d", "[6] e", "[7] f", "[8] g"]]
    ok = split_paragraphs(pages, "bracket", skips=[2])
    assert validate_award({**META, "skips": [2], "reasoning_from": 3}, ok, text) == []
    stopped = split_paragraphs(pages, "bracket")
    problems = validate_award({**META, "reasoning_from": 1, "min_reasoning": 1}, stopped, text)
    assert any("numbering stops after para 1" in p for p in problems)


def test_reasoning_ranges_leave_out_the_parties_submissions_in_between():
    pages = [[f"[{n}] text {n}." for n in range(1, 9)]]
    paragraphs = split_paragraphs(pages, "bracket")
    meta = {**META, "reasoning": [[2, 3], [6, 8]]}
    assert [c["paragraph"] for c in award_chunks(meta, paragraphs, [])] == [2, 3, 6, 7, 8]


def test_validation_checks_ranges_and_reads_a_slash_award_number():
    text = "AWARD NO.: 1806 / 2025\nCASE NO: 10/4-1123 / 24\n" + "\n".join(f"[{n}] t" for n in range(1, 9))
    paragraphs = split_paragraphs([[f"[{n}] t" for n in range(1, 9)]], "bracket")
    assert validate_award({**META, "reasoning": [[2, 8]], "min_reasoning": 2}, paragraphs, text) == []
    problems = validate_award({**META, "reasoning": [[6, 12]], "min_reasoning": 2}, paragraphs, text)
    assert any("reasoning range [6, 12] outside 1..8" in p for p in problems)


def test_statute_names_broken_across_lines_are_found():
    assert statutes_applied("section 29(d) of the Industrial\nRelations Act 1967 and the Labour\nOrdinance (Sabah Cap. 67)") == \
        ["Industrial Relations Act 1967", "Labour Ordinance (Sabah)"]


def test_award_number_written_with_year():
    text = "AWARD NO: 1812 OF YEAR 2025\nCASE NO: 10/4-1123/24\n" + "\n".join(f"[{n}] t" for n in range(1, 9))
    paragraphs = split_paragraphs([[f"[{n}] t" for n in range(1, 9)]], "bracket")
    meta = {**META, "award_number": "1812 of 2025", "reasoning": [[2, 8]], "min_reasoning": 2}
    assert validate_award(meta, paragraphs, text) == []


def test_a_heading_after_a_paragraph_becomes_the_next_paragraphs_section_title():
    pages = [["[1] Facts here.", " ", "THE LAW AND BURDEN OF PROOF", " ", "[2] The burden is on the employer.",
              "Evaluation of Evidence & Findings:", "[3] The Court finds.", "[4] Still findings, citing", "Ireka Construction Berhad v Chantiravathan"]]
    paragraphs = split_paragraphs(pages, "bracket")
    assert paragraphs[0].text == "Facts here."
    assert [p.heading for p in paragraphs] == [None, "THE LAW AND BURDEN OF PROOF", "Evaluation of Evidence & Findings",
                                               "Evaluation of Evidence & Findings"]
    assert paragraphs[3].text.endswith("Ireka Construction Berhad v Chantiravathan")  # a case name is not a heading
    chunks = award_chunks({**META, "reasoning": [[2, 4]]}, paragraphs, [])
    assert chunks[0]["section_title"] == "THE LAW AND BURDEN OF PROOF"


def test_transcript_lines_stay_in_the_paragraph():
    pages = [["[1] Cross-examination:", "Soalan: Kamu setuju?", "TAMIL", "Ya. Setuju", "[2] Next."]]
    paragraphs = split_paragraphs(pages, "bracket")
    assert paragraphs[0].text.endswith("TAMIL Ya. Setuju") and paragraphs[1].heading is None


def test_a_heading_printed_one_word_per_line_is_still_a_heading():
    words = ["WHETHER", "THE", "DISMISSAL", "IS", "PROPORTIONATE", "TO", "THE", "ALLEGED", "MISCONDUCT"]
    paragraphs = split_paragraphs([["[1] Facts."] + words + ["[2] Findings."]], "bracket")
    assert paragraphs[0].text == "Facts."
    assert paragraphs[1].heading == "WHETHER THE DISMISSAL IS PROPORTIONATE TO THE ALLEGED MISCONDUCT"


def test_a_lone_table_word_is_not_a_heading():
    paragraphs = split_paragraphs([["[1] Back wages RM10,000.00", "TOTAL", "[2] Next."]], "bracket")
    assert paragraphs[0].text.endswith("TOTAL") and paragraphs[1].heading is None


def test_a_title_ending_an_unfinished_sentence_stays_with_its_paragraph():
    pages = [["[1] The Claimant was appointed as", "Senior Manager", "[2] Next."]]
    paragraphs = split_paragraphs(pages, "bracket")
    assert paragraphs[0].text == "The Claimant was appointed as Senior Manager" and paragraphs[1].heading is None


def test_a_speaker_label_and_a_one_word_answer_are_not_a_heading():
    pages = [["[1] Soalan: Kamu setuju?", "TAMIL", "Setuju", "[2] Next."]]
    paragraphs = split_paragraphs(pages, "bracket")
    assert paragraphs[0].text.endswith("TAMIL Setuju") and paragraphs[1].heading is None


def test_a_bracketed_line_can_continue_a_heading():
    pages = [["[1] Text.", "THE HEIGHTENED STATUTORY BURDEN", "(PREGNANCY DISCRIMINATION)", "[2] Next."]]
    paragraphs = split_paragraphs(pages, "bracket")
    assert paragraphs[1].heading == "THE HEIGHTENED STATUTORY BURDEN (PREGNANCY DISCRIMINATION)"


def test_an_answer_line_after_a_question_is_not_a_heading():
    pages = [["[1] RK", "Kamu setuju kamu tidak pernah declare, setuju?", "TAMIL Setuju", "[2] Next."]]
    paragraphs = split_paragraphs(pages, "bracket")
    assert paragraphs[0].text.endswith("setuju? TAMIL Setuju") and paragraphs[1].heading is None


def test_short_sentence_case_and_labelled_headings():
    cases = [(["The Law"], "The Law"), (["The court’s findings"], "The court’s findings"),
             (["B.", "The Principles from Ng Chang Seng’ case"], "B. The Principles from Ng Chang Seng’ case"),
             (["REMEDIES", "a) Reinstatement"], "REMEDIES a) Reinstatement")]
    for lines, heading in cases:
        paragraphs = split_paragraphs([["[1] The Company dismissed him."] + lines + ["[2] Next."]], "bracket")
        assert paragraphs[0].text == "The Company dismissed him.", lines
        assert paragraphs[1].heading == heading


def test_a_heading_after_a_capitalised_line_without_a_full_stop():
    pages = [["[1] In other words, the absence of a party does not entail the consequence that an",
              "Award will straightaway be made against him”"], ["ISSUES", "", "[2] The issues are:"]]
    paragraphs = split_paragraphs(pages, "bracket")
    assert paragraphs[0].text.endswith("against him”") and paragraphs[1].heading == "ISSUES"


def test_a_dash_after_a_colon_keeps_its_space():
    assert join_lines(["The issues that arise are:-", "(i) whether"]) == "The issues that arise are:- (i) whether"
