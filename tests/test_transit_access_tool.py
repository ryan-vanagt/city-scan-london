"""Tests for the get_transit_access agent tool."""

from pathlib import Path

import pytest

from agents.tools.transit_access import _DATA_PATH, get_transit_access

DATA_EXISTS = _DATA_PATH.exists()


@pytest.fixture(autouse=True)
def _reset_cache():
    import agents.tools.transit_access as mod
    mod._ptal_data = None
    yield
    mod._ptal_data = None


@pytest.mark.skipif(not DATA_EXISTS, reason="transit_access.json not generated")
def test_get_by_name() -> None:
    result = get_transit_access("City of London")
    assert "error" not in result
    assert result["borough_code"] == "E09000001"
    assert result["ptal_band"] == "6b"


@pytest.mark.skipif(not DATA_EXISTS, reason="transit_access.json not generated")
def test_get_by_ons_code() -> None:
    result = get_transit_access("E09000016")  # Havering
    assert "error" not in result
    assert result["borough_name"] == "Havering"


def test_unknown_borough() -> None:
    result = get_transit_access("Atlantis-on-Sea")
    assert "error" in result


def test_empty_string() -> None:
    result = get_transit_access("")
    assert "error" in result


def test_input_length_cap() -> None:
    result = get_transit_access("X" * 1000)
    assert "error" in result


@pytest.mark.skipif(not DATA_EXISTS, reason="transit_access.json not generated")
def test_returns_vintage_disclosure() -> None:
    """Tool should always return the 2015 vintage so the LLM can disclose it."""
    result = get_transit_access("Westminster")
    assert result["vintage"] == 2015


@pytest.mark.skipif(not DATA_EXISTS, reason="transit_access.json not generated")
def test_returns_normalised_score() -> None:
    result = get_transit_access("Westminster")
    score = result["score_0_to_100"]
    assert score is not None and 0 <= score <= 100


def test_missing_file_returns_error(monkeypatch, tmp_path) -> None:
    import agents.tools.transit_access as mod
    monkeypatch.setattr(mod, "_DATA_PATH", tmp_path / "missing.json")
    mod._ptal_data = None
    result = mod.get_transit_access("Camden")
    assert "error" in result
