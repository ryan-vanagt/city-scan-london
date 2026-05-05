"""Unit tests for the composite-flag derivation rule.

The rule itself is small but load-bearing: it converts the live input
organs' bootstrap flags into a single quality flag for the composite
score that the tooltip and bulletin both read.
"""

import pytest

from scripts.compute_score_quality import _derive_composite_flag


@pytest.mark.parametrize(
    "air,transit,immune,expected_flag",
    [
        ("green", "green", "green", "green"),
        ("amber", "green", "green", "green"),
        ("green", "green", "amber", "green"),
        ("amber", "amber", "green", "amber"),
        ("amber", "amber", "amber", "amber"),
        ("red", "green", "green", "amber"),
        ("red", "amber", "green", "amber"),
        ("red", "red", "green", "red"),
        ("red", "red", "red", "red"),
    ],
)
def test_derive_composite_flag_rules(air, transit, immune, expected_flag):
    flag, _ = _derive_composite_flag(air, transit, immune)
    assert flag == expected_flag


def test_derive_composite_flag_basis_counts_match_inputs():
    flag, basis = _derive_composite_flag("red", "amber", "green")
    assert flag == "amber"
    assert "1 red" in basis
    assert "1 amber" in basis
    assert "1 green" in basis


def test_derive_composite_flag_all_green_basis():
    _, basis = _derive_composite_flag("green", "green", "green")
    assert "0 red" in basis
    assert "0 amber" in basis
    assert "3 green" in basis


def test_derive_composite_flag_input_order_invariant():
    f1, _ = _derive_composite_flag("red", "amber", "green")
    f2, _ = _derive_composite_flag("green", "red", "amber")
    f3, _ = _derive_composite_flag("amber", "green", "red")
    assert f1 == f2 == f3 == "amber"
