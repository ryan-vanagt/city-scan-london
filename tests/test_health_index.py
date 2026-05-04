"""Tests for ONS Health Index data integrity."""

import json
from pathlib import Path

import pytest

DATA_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "static" / "ons_health_index.json"
)

# Health Index excludes City of London (E09000001) by ONS convention.
EXPECTED_CODES = {
    f"E0900{str(i).zfill(4)}" for i in range(2, 34)
}  # 32 boroughs (2..33)


@pytest.fixture(scope="module")
def hi_data() -> dict:
    if not DATA_PATH.exists():
        pytest.skip(
            "Health Index data not generated — run "
            "scripts/refresh_ons_health_index.py first"
        )
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_32_boroughs(hi_data: dict) -> None:
    """ONS excludes City of London — 32 boroughs is correct."""
    boroughs = hi_data["boroughs"]
    assert len(boroughs) == 32, f"Expected 32 boroughs (CoL excluded), got {len(boroughs)}"


def test_city_of_london_excluded(hi_data: dict) -> None:
    assert "E09000001" not in hi_data["boroughs"], (
        "City of London should be excluded from Health Index — ONS doesn't publish for it"
    )


def test_all_expected_codes_present(hi_data: dict) -> None:
    found = set(hi_data["boroughs"].keys())
    missing = EXPECTED_CODES - found
    assert not missing, f"Missing borough codes: {missing}"


def test_metadata_present(hi_data: dict) -> None:
    meta = hi_data.get("_metadata", {})
    assert "ONS Health Index" in meta.get("source", "")
    assert "url" in meta
    assert isinstance(meta.get("year"), int)
    assert "Table 2" in meta.get("table", "")
    assert "lag_note" in meta


def test_scores_in_plausible_range(hi_data: dict) -> None:
    """England-2015 = 100. All London boroughs in 2021 land roughly 80–125."""
    year = hi_data["_metadata"]["year"]
    score_key = f"score_{year}"
    for code, b in hi_data["boroughs"].items():
        score = b[score_key]
        assert score is None or 70.0 <= score <= 130.0, (
            f"{b['name']} score {score} outside plausible range 70–130"
        )


def test_richmond_top(hi_data: dict) -> None:
    """Richmond upon Thames historically tops the London Health Index."""
    year = hi_data["_metadata"]["year"]
    score_key = f"score_{year}"
    items = [
        (b["name"], b[score_key])
        for b in hi_data["boroughs"].values()
        if b[score_key] is not None
    ]
    items.sort(key=lambda x: -x[1])
    top_name, _ = items[0]
    assert top_name == "Richmond upon Thames", (
        f"Expected Richmond upon Thames at top, got {top_name}"
    )


def test_no_duplicate_borough_names(hi_data: dict) -> None:
    names = [b["name"] for b in hi_data["boroughs"].values()]
    assert len(names) == len(set(names)), "Duplicate borough names found"


def test_loader_function() -> None:
    """The API loader function should produce the response shape consumed by the frontend."""
    if not DATA_PATH.exists():
        pytest.skip("Health Index data not generated")
    try:
        from api.routers.boroughs import _load_health_index_data
    except ModuleNotFoundError as exc:
        pytest.skip(f"API deps not installed locally ({exc.name}); run on server / in CI")
    _load_health_index_data.cache_clear()
    rows = _load_health_index_data()
    assert len(rows) == 32
    assert all("borough_code" in r and "borough_name" in r for r in rows)
    assert all("score" in r for r in rows)
    assert all(r["year"] is not None for r in rows)
