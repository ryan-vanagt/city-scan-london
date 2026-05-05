"""Tests for the TfL PTAL transit-access static dataset."""

import json
from pathlib import Path

import pytest

DATA_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "static" / "transit_access.json"
)

EXPECTED_CODES = {f"E0900{str(i).zfill(4)}" for i in range(1, 34)}


@pytest.fixture(scope="module")
def ptal_data() -> dict:
    if not DATA_PATH.exists():
        pytest.skip(
            "PTAL data not generated — run scripts/fetch_ptal.py first"
        )
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_metadata_present(ptal_data: dict) -> None:
    meta = ptal_data.get("_metadata", {})
    assert "TfL" in meta.get("source", "")
    assert "url" in meta
    assert isinstance(meta.get("vintage"), int)
    assert "definition" in meta


def test_all_33_boroughs(ptal_data: dict) -> None:
    boroughs = ptal_data["boroughs"]
    assert len(boroughs) == 33


def test_all_expected_codes_present(ptal_data: dict) -> None:
    found = set(ptal_data["boroughs"].keys())
    missing = EXPECTED_CODES - found
    assert not missing


def test_scores_in_0_to_100_range(ptal_data: dict) -> None:
    for code, b in ptal_data["boroughs"].items():
        score = b["score_0_to_100"]
        assert score is None or 0.0 <= score <= 100.0, (
            f"{b['name']} score {score} outside 0-100 range"
        )


def test_ptal_bands_valid(ptal_data: dict) -> None:
    """PTAL bands run 1a (lowest) → 6b (highest). Empty / 0 is also acceptable."""
    valid_bands = {"0", "1a", "1b", "2", "3", "4", "5", "6a", "6b", ""}
    for code, b in ptal_data["boroughs"].items():
        band = b.get("ptal_band", "")
        assert band in valid_bands, f"{b['name']} has invalid PTAL band: {band!r}"


def test_avptai_present_and_positive(ptal_data: dict) -> None:
    for code, b in ptal_data["boroughs"].items():
        avptai = b.get("avptai_2015")
        assert avptai is not None and avptai > 0, (
            f"{b['name']} missing or non-positive AvPTAI: {avptai}"
        )


def test_city_of_london_top(ptal_data: dict) -> None:
    """City of London has by far the densest transit network — should top the
    list. (Sanity check: confirms the log-transform doesn't invert the order.)"""
    items = sorted(
        ptal_data["boroughs"].items(),
        key=lambda x: -(x[1]["score_0_to_100"] or 0),
    )
    top_code = items[0][0]
    assert top_code == "E09000001", (
        f"Expected City of London (E09000001) at top, got {top_code}"
    )


def test_havering_or_outer_at_bottom(ptal_data: dict) -> None:
    """Outer eastern boroughs have the lowest PTAL scores. Havering, Bexley,
    Bromley, Hillingdon — at least one of them should bottom the list."""
    outer_eastern = {"E09000016", "E09000004", "E09000006", "E09000017"}
    items = sorted(
        ptal_data["boroughs"].items(),
        key=lambda x: (x[1]["score_0_to_100"] or 0),
    )
    bottom_code = items[0][0]
    assert bottom_code in outer_eastern, (
        f"Expected an outer eastern borough at bottom, got {bottom_code}"
    )


def test_no_duplicate_borough_names(ptal_data: dict) -> None:
    names = [b["name"] for b in ptal_data["boroughs"].values()]
    assert len(names) == len(set(names))


def test_loader_function() -> None:
    if not DATA_PATH.exists():
        pytest.skip("PTAL data not generated")
    try:
        from api.routers.boroughs import _load_ptal_data
    except ModuleNotFoundError as exc:
        pytest.skip(f"API deps not installed locally ({exc.name})")
    _load_ptal_data.cache_clear()
    rows = _load_ptal_data()
    assert len(rows) == 33
    assert all("borough_code" in r and "score" in r for r in rows)
    assert all(r["vintage"] == 2015 for r in rows)
