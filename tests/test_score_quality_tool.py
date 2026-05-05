"""Tests for the get_score_quality agent tool."""

import json
from pathlib import Path

import pytest

from agents.tools.score_quality import (
    _DATA_PATH,
    _load_data,
    _resolve_borough,
    get_score_quality,
)

DATA_EXISTS = _DATA_PATH.exists()


@pytest.fixture(autouse=True)
def _reset_cache():
    """Clear the module-level cache before each test."""
    import agents.tools.score_quality as mod
    mod._quality_data = None
    yield
    mod._quality_data = None


@pytest.mark.skipif(not DATA_EXISTS, reason="score_quality.json not generated")
def test_load_data_returns_dict() -> None:
    data = _load_data()
    assert isinstance(data, dict)
    assert "boroughs" in data


@pytest.mark.skipif(not DATA_EXISTS, reason="score_quality.json not generated")
def test_get_score_quality_by_name() -> None:
    result = get_score_quality("Westminster")
    assert "error" not in result
    assert result["borough_name"] == "Westminster"
    assert result["borough_code"] == "E09000033"
    assert "organs" in result
    # Westminster should have a green composite (low residual variability) and
    # an amber sentiment (London-wide signal)
    organs = result["organs"]
    assert "composite_score" in organs
    assert organs["sentiment_score"]["flag"] == "amber"


@pytest.mark.skipif(not DATA_EXISTS, reason="score_quality.json not generated")
def test_get_score_quality_by_ons_code() -> None:
    result = get_score_quality("E09000012")  # Hackney
    assert "error" not in result
    assert result["borough_code"] == "E09000012"
    assert result["borough_name"] == "Hackney"


def test_get_score_quality_unknown_borough() -> None:
    result = get_score_quality("Atlantis-on-Sea")
    assert "error" in result
    assert "Atlantis-on-Sea" in result["error"]


def test_get_score_quality_empty_string() -> None:
    result = get_score_quality("")
    assert "error" in result


def test_get_score_quality_input_length_cap() -> None:
    """Borough input is capped at 100 chars in the tool wrapper. The core
    function should still handle very long input gracefully."""
    result = get_score_quality("A" * 1000)
    assert "error" in result


@pytest.mark.skipif(not DATA_EXISTS, reason="score_quality.json not generated")
def test_resolve_borough_handles_partial_match() -> None:
    """'Hackney' matches uniquely; 'Hack' should also match starts-with."""
    resolved = _resolve_borough("Hack")
    assert resolved is not None
    code, b = resolved
    assert code == "E09000012"


def test_missing_file_returns_empty_dict(monkeypatch, tmp_path) -> None:
    """If the data file is missing, _load_data returns {} without crashing."""
    import agents.tools.score_quality as mod
    monkeypatch.setattr(mod, "_DATA_PATH", tmp_path / "nonexistent.json")
    mod._quality_data = None
    data = mod._load_data()
    assert data == {}
    # Tool should then return an error for any lookup
    result = mod.get_score_quality("Westminster")
    assert "error" in result
