"""Tests for the get_housing_affordability agent tool."""

from pathlib import Path

import pytest

from agents.tools.housing_affordability import (
    _DATA_PATH,
    _load_data,
    _resolve_borough,
    get_housing_affordability,
)

DATA_EXISTS = _DATA_PATH.exists()


@pytest.fixture(autouse=True)
def _reset_cache():
    import agents.tools.housing_affordability as mod
    mod._housing_data = None
    yield
    mod._housing_data = None


@pytest.mark.skipif(not DATA_EXISTS, reason="housing_affordability.json not generated")
def test_get_by_name() -> None:
    result = get_housing_affordability("Kensington and Chelsea")
    assert "error" not in result
    assert result["borough_code"] == "E09000020"
    assert result["ratio"] is not None
    assert result["ratio"] > 20  # K&C historically tops the list


@pytest.mark.skipif(not DATA_EXISTS, reason="housing_affordability.json not generated")
def test_get_by_ons_code() -> None:
    result = get_housing_affordability("E09000030")  # Tower Hamlets
    assert "error" not in result
    assert result["borough_name"] == "Tower Hamlets"


@pytest.mark.skipif(not DATA_EXISTS, reason="housing_affordability.json not generated")
def test_get_all_when_no_borough() -> None:
    result = get_housing_affordability(None)
    assert "boroughs" in result
    assert len(result["boroughs"]) == 33
    # First entry should be most expensive (sorted descending)
    assert result["boroughs"][0]["borough_name"] == "Kensington and Chelsea"
    # Last entry should be most affordable
    assert result["boroughs"][-1]["borough_name"] == "Tower Hamlets"


@pytest.mark.skipif(not DATA_EXISTS, reason="housing_affordability.json not generated")
def test_get_all_when_empty_string() -> None:
    """Empty string should be treated as 'all boroughs' (matches the
    LangChain wrapper behaviour)."""
    result = get_housing_affordability("")
    assert "boroughs" in result
    assert len(result["boroughs"]) == 33


def test_unknown_borough() -> None:
    result = get_housing_affordability("Atlantis-on-Sea")
    assert "error" in result


def test_input_length_cap() -> None:
    result = get_housing_affordability("X" * 1000)
    assert "error" in result


def test_missing_file_returns_empty(monkeypatch, tmp_path) -> None:
    import agents.tools.housing_affordability as mod
    monkeypatch.setattr(mod, "_DATA_PATH", tmp_path / "missing.json")
    mod._housing_data = None
    result = mod.get_housing_affordability("Camden")
    assert "error" in result


@pytest.mark.skipif(not DATA_EXISTS, reason="housing_affordability.json not generated")
def test_5yr_avg_present_when_borough_specified() -> None:
    result = get_housing_affordability("Westminster")
    assert "ratio_5yr_avg" in result
    assert result["ratio_5yr_avg"] is not None
