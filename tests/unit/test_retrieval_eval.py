"""Tests for src/evaluation/retrieval_eval.py: retrieval metrics and cross-validated abstention."""
import pytest

from src.evaluation.retrieval_eval import hit_at_k, kfold_abstention, recall, reciprocal_rank


class TestRankMetrics:
    def test_hit_when_any_expected_chunk_is_in_the_top_k(self):
        assert hit_at_k(["a", "b", "c"], ["c", "z"], k=3)
        assert not hit_at_k(["a", "b", "c"], ["c"], k=2)

    def test_recall_is_the_share_of_expected_chunks_found(self):
        assert recall(["a", "b"], ["a", "c"]) == pytest.approx(0.5)
        assert recall(["a", "c"], ["a", "c"]) == 1.0

    def test_recall_of_nothing_expected_is_undefined(self):
        with pytest.raises(ValueError):
            recall(["a"], [])

    def test_reciprocal_rank_of_the_first_expected_chunk(self):
        assert reciprocal_rank(["x", "a", "b"], ["b", "a"]) == pytest.approx(0.5)
        assert reciprocal_rank(["x", "y"], ["a"]) == 0.0


# (id, gate score, in scope?)
ITEMS = [(f"in{i}", 0.5 + i / 100, True) for i in range(10)] + [(f"out{i}", 0.01 * i, False) for i in range(5)]


class TestKfold:
    def test_every_item_is_tested_exactly_once(self):
        result = kfold_abstention(ITEMS, budget=0.1, k=5)
        assert sorted(result["tested_ids"]) == sorted(i for i, _, _ in ITEMS)

    def test_folds_are_deterministic(self):
        assert kfold_abstention(ITEMS, budget=0.1, k=5) == kfold_abstention(ITEMS, budget=0.1, k=5)

    def test_separated_scores_decline_all_out_of_scope(self):
        result = kfold_abstention(ITEMS, budget=0.1, k=5)
        assert result["out_of_scope_declined"] == 1.0
        # The lowest in-scope item (in0) is held out in its fold; the threshold
        # learnt without it is the next score up, so it is declined: 1 of 10.
        assert result["in_scope_declined"] == pytest.approx(0.1)

    def test_each_fold_threshold_comes_from_the_other_folds(self):
        # The lowest in-scope score sits in one test fold; with budget 0 the
        # threshold of that fold is chosen without it, so it is declined there.
        items = [("low", 0.2, True)] + [(f"in{i}", 0.9, True) for i in range(4)] + [("o", 0.0, False)]
        result = kfold_abstention(items, budget=0.0, k=5)
        assert result["in_scope_declined"] == pytest.approx(1 / 5)
