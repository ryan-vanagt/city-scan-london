"""Tests for the get_health_index agent tool."""

from pathlib import Path

import pytest

from agents.tools.health_index import (
    _CITY_OF_LONDON_CODE,
    _DATA_PATH,
    _load_data,
    _resolve_borough,
    get_health_index,
)

DATA_EXISTS = _DATA_PATH.exists()


@pytest.fixture(autouse=True)
def _reset_cache():
    import agents.tools.health_index as mod
    mod._hi_data = None
    yield
    mod._hi_data = None


@pytest.mark.skipif(not DATA_EXISTS, reason="ons_health_index.json not generated")
def test_get_by_name() -> None:
    result = get_health_index("Richmond upon Thames")
    assert "error" not in result
    assert result["borough_code"] == "E09000027"
    assert result["score"] is not None
    assert 100 < result["score"] < 130  # Richmond historically tops London


@pytest.mark.skipif(not DATA_EXISTS, reason="ons_health_index.json not generated")
def test_get_by_ons_code() -> None:
    result = get_health_index("E09000028")  # Southwark
    assert "error" not in result
    assert result["borough_name"] == "Southwark"
    assert result["score"] is not None


def test_city_of_london_returns_not_in_dataset() -> None:
    """ONS excludes City of London — the tool should return a structured
    response rather than a generic error."""
    result = get_health_index("City of London")
    assert result.get("not_in_dataset") is True
    assert result["borough_code"] == _CITY_OF_LONDON_CODE
    assert "reason" in result


def test_city_of_london_by_code_also_handled() -> None:
    result = get_health_index(_CITY_OF_LONDON_CODE)
    assert result.get("not_in_dataset") is True


def test_unknown_borough() -> None:
    result = get_health_index("Atlantis-on-Sea")
    assert "error" in result


def test_empty_string() -> None:
    result = get_health_index("")
    assert "error" in result


def test_input_length_cap() -> None:
    result = get_health_index("X" * 1000)
    assert "error" in result


@pytest.mark.skipif(not DATA_EXISTS, reason="ons_health_index.json not generated")
def test_returns_baseline_year_for_context() -> None:
    """Tool should return 2015 baseline + 2020 context score so the LLM
    can describe trajectory."""
    result = get_health_index("Hackney")
    assert "score_2015" in result
    assert "score_2020" in result


def test_missing_file_returns_empty(monkeypatch, tmp_path) -> None:
    import agents.tools.health_index as mod
    monkeypatch.setattr(mod, "_DATA_PATH", tmp_path / "missing.json")
    mod._hi_data = None
    result = mod.get_health_index("Camden")
    # CoL is special-cased and doesn't need the file; other boroughs error
    assert "error" in result
