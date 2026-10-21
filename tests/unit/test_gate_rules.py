"""Tests for src/evaluation/gate_rules.py."""
import pytest

from src.evaluation.gate_rules import STOPPED, Scored, fold_votes, kfold, passes, select_oos_threshold, tune


def item(id_, in_scope, orig, rew, fold_of=None):
    return Scored(id=id_, in_scope=in_scope, orig=orig, rew=rew, fold_of=fold_of or id_)


def test_select_oos_threshold_declines_at_least_70_percent():
    oos = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    t = select_oos_threshold(oos)
    assert sum(s < t for s in oos) == 7
    assert 0.7 < t < 0.8


def test_score_equal_to_threshold_passes():
    assert passes("baseline", item("a", True, 0.5, 0.0), {"t": 0.5}) == (True, "orig")
    assert passes("baseline", item("a", True, 0.4999, 0.0), {"t": 0.5})[0] is False


def test_stopped_original_is_declined_by_baseline():
    it = item("a-ms", True, STOPPED, 0.9)
    assert passes("baseline", it, {"t": 0.0})[0] is False
    assert passes("rewrite", it, {"t": 0.5}) == (True, "rew")


def test_max_takes_source_of_higher_score():
    assert passes("max", item("a", True, 0.2, 0.6), {"t": 0.5}) == (True, "rew")
    assert passes("max", item("a", True, 0.6, 0.6), {"t": 0.5}) == (True, "orig")
    assert passes("max", item("a", True, 0.2, 0.3), {"t": 0.5}) == (False, "rew")


def test_or_strict_uses_rewrite_only_above_its_own_threshold():
    params = {"t_o": 0.5, "t_r": 0.8}
    assert passes("or_strict", item("a", True, 0.6, 0.0), params) == (True, "orig")
    assert passes("or_strict", item("a", True, 0.1, 0.9), params) == (True, "rew")
    assert passes("or_strict", item("a", True, 0.1, 0.7), params)[0] is False


def test_band_uses_rewrite_only_inside_the_band():
    params = {"t": 0.5, "low": 0.3}
    assert passes("band", item("a", True, 0.4, 0.9), params) == (True, "rew")
    assert passes("band", item("a", True, 0.2, 0.9), params)[0] is False
    assert passes("band", item("a", True, 0.6, 0.0), params) == (True, "orig")


def _oos(scores_orig, scores_rew):
    return [item(f"O{i}", False, o, r) for i, (o, r) in enumerate(zip(scores_orig, scores_rew))]


def test_or_strict_falls_back_to_baseline_when_rewrite_cannot_help():
    # Any rewrite threshold that lets the in-scope item through also lets every out-of-scope item through.
    train = _oos([0.1] * 10, [0.99] * 10) + [item("I0", True, 0.05, 0.99)]
    params = tune("or_strict", train)
    assert params["t_r"] > 0.99
    assert passes("or_strict", train[-1], params)[0] is False
    assert not any(passes("or_strict", o, params)[0] for o in train[:-1])


def test_or_strict_picks_lowest_safe_rewrite_threshold():
    train = _oos([0.1] * 10, [0.2] * 10) + [item("I0", True, 0.05, 0.9)]
    params = tune("or_strict", train)
    assert 0.2 < params["t_r"] <= 0.9
    assert passes("or_strict", train[-1], params) == (True, "rew")


def test_band_empty_when_any_band_breaches_constraint():
    train = _oos([0.1] * 10, [0.99] * 10) + [item("I0", True, 0.09, 0.99)]
    params = tune("band", train)
    assert params["low"] == params["t"]


def test_band_rescues_near_miss_in_scope_item():
    train = _oos([0.01] * 7 + [0.5, 0.6, 0.7], [0.01] * 10) + [item("I0", True, 0.005, 0.9)]
    params = tune("band", train)
    assert passes("band", train[-1], params) == (True, "rew")


def _fold_set():
    oos = [item(f"O{i}", False, i / 10, 0.0) for i in range(10)]
    ins = [item(f"I{i}", True, 1.0, 0.0) for i in range(5)]
    return oos + ins


def test_kfold_uses_retrieval_eval_fold_assignment():
    result = kfold("baseline", _fold_set())
    folds = {i: d["fold"] for i, d in result["decisions"].items()}
    assert [folds[f"O{i}"] for i in range(10)] == [0, 1, 2, 3, 4, 0, 1, 2, 3, 4]
    assert [folds[f"I{i}"] for i in range(5)] == [0, 1, 2, 3, 4]


def test_kfold_reports_held_out_rate_not_training():
    # Training folds each decline 6 of 8 (75%); held-out: 2 + 2 + 1 + 1 + 1 = 7 of 10.
    result = kfold("baseline", _fold_set())
    assert result["out_of_scope_declined"] == pytest.approx(0.7)
    assert result["in_scope_declined"] == 0.0
    assert [round(p["t"], 6) for p in result["fold_params"]] == [0.7, 0.7, 0.6, 0.6, 0.6]


def test_malay_variant_uses_parent_fold_and_is_excluded_from_rates():
    items = _fold_set() + [item("I2-ms", True, STOPPED, 0.0, fold_of="I2"), item("I3-ms", True, STOPPED, 1.0, fold_of="I3")]
    result = kfold("rewrite", items)
    assert result["decisions"]["I2-ms"]["fold"] == result["decisions"]["I2"]["fold"]
    assert result["decisions"]["I2-ms"]["passed"] is False and result["decisions"]["I3-ms"]["passed"] is True
    baseline_only = kfold("rewrite", _fold_set())
    assert result["in_scope_declined"] == baseline_only["in_scope_declined"]
    assert result["out_of_scope_declined"] == baseline_only["out_of_scope_declined"]


def test_fold_votes_applies_each_fold_params_to_an_unfolded_item():
    # External items take part in no fold; each fold's tuned parameters are applied to them.
    params = [{"t": 0.5}, {"t": 0.2}, {"t": 0.9}]
    votes = fold_votes("baseline", item("SWK-033", False, 0.3, 0.0), params)
    assert votes == [(False, "orig"), (True, "orig"), (False, "orig")]
