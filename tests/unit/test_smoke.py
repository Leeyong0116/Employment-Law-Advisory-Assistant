"""Tests for src/indexing/smoke.py (the matching rule; the checks themselves
need the model and database and run as `python -m src.indexing.smoke`)."""
from src.indexing import smoke


def test_a_section_matches_its_own_chunks():
    assert smoke.matches("IRA1967_s5_1", ("IRA1967_s5",))
    assert smoke.matches("IRA1967_sch1", ("IRA1967_sch1",))


def test_a_longer_section_number_is_not_a_match():
    # Found in the first smoke run: s.59 was counted as a hit for s.5.
    assert not smoke.matches("IRA1967_s59_1", ("IRA1967_s5",))
    assert not smoke.matches("EA1955_s60EA_1", ("EA1955_s60E",))


def test_every_check_names_at_least_one_expected_section():
    assert all(check.expect_prefixes for check in smoke.CHECKS)
