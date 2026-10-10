"""Tests for src/evaluation/calibration.py: threshold sweep arithmetic."""
import pytest

from src.evaluation.calibration import rates, roc_auc, select_threshold

# (gate score, in scope?)
ITEMS = [(0.9, True), (0.8, True), (0.4, True), (0.2, True), (0.3, False), (0.05, False), (0.0, False), (0.01, False)]


def test_rates_at_a_threshold():
    r = rates(ITEMS, 0.25)
    # out of scope declined: 0.05, 0.0, 0.01 (0.3 is answered) -> 3/4
    assert r["out_of_scope_declined"] == pytest.approx(0.75)
    # in scope wrongly declined: 0.2 -> 1/4
    assert r["in_scope_declined"] == pytest.approx(0.25)


def test_score_equal_to_threshold_is_answered():
    assert rates([(0.3, True)], 0.3)["in_scope_declined"] == 0.0


def test_auc_perfect_and_chance():
    assert roc_auc([(0.9, True), (0.1, False)]) == 1.0
    assert roc_auc([(0.5, True), (0.5, False)]) == 0.5


def test_auc_counts_misordered_pairs():
    # 4 in x 4 out = 16 pairs; only (0.2 in, 0.3 out) is misordered
    assert roc_auc(ITEMS) == pytest.approx(15 / 16)


def test_select_highest_threshold_within_the_in_scope_budget():
    # budget 0.25: may decline one of four in-scope items, so threshold up to 0.4
    assert select_threshold(ITEMS, max_in_scope_declined=0.25) == pytest.approx(0.4)
    # budget 0: may decline none, so threshold is the lowest in-scope score
    assert select_threshold(ITEMS, max_in_scope_declined=0.0) == pytest.approx(0.2)


def test_select_needs_in_scope_items():
    with pytest.raises(ValueError):
        select_threshold([(0.1, False)], max_in_scope_declined=0.1)
