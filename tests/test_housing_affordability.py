"""Tests for ONS housing affordability data integrity."""

import json
from pathlib import Path

import pytest

DATA_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "static" / "housing_affordability.json"
)

EXPECTED_CODES = {f"E0900{str(i).zfill(4)}" for i in range(1, 34)}


@pytest.fixture(scope="module")
def housing_data() -> dict:
    """Load housing affordability data, skip if file not generated yet."""
    if not DATA_PATH.exists():
        pytest.skip(
            "Housing affordability data not generated — run "
            "scripts/refresh_housing_affordability.py first"
        )
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_all_33_boroughs(housing_data: dict) -> None:
    boroughs = housing_data["boroughs"]
    assert len(boroughs) == 33, f"Expected 33 boroughs, got {len(boroughs)}"


def test_all_expected_codes_present(housing_data: dict) -> None:
    found = set(housing_data["boroughs"].keys())
    missing = EXPECTED_CODES - found
    assert not missing, f"Missing borough codes: {missing}"


def test_metadata_present(housing_data: dict) -> None:
    meta = housing_data.get("_metadata", {})
    assert "source" in meta and "ONS" in meta["source"]
    assert "url" in meta
    assert isinstance(meta.get("year"), int)
    assert meta.get("table") == "5c"


def test_ratios_in_plausible_range(housing_data: dict) -> None:
    """London affordability ratios are bounded — sanity-check we didn't grab the wrong column.

    Even the lowest London ratio is comfortably above the national median (~5–8),
    and the highest is bounded by Kensington & Chelsea historically near ~40.
    """
    year = housing_data["_metadata"]["year"]
    ratio_key = f"ratio_{year}"
    for code, b in housing_data["boroughs"].items():
        ratio = b[ratio_key]
        assert ratio is None or 5.0 <= ratio <= 50.0, (
            f"{b['name']} ratio {ratio} outside plausible range 5–50"
        )


def test_no_duplicate_borough_names(housing_data: dict) -> None:
    names = [b["name"] for b in housing_data["boroughs"].values()]
    assert len(names) == len(set(names)), "Duplicate borough names found"


def test_kensington_chelsea_top(housing_data: dict) -> None:
    """Cross-check: K&C should historically be the most expensive borough by ratio."""
    year = housing_data["_metadata"]["year"]
    ratio_key = f"ratio_{year}"
    items = [
        (b["name"], b[ratio_key])
        for b in housing_data["boroughs"].values()
        if b[ratio_key] is not None
    ]
    items.sort(key=lambda x: -x[1])
    top_name, _ = items[0]
    assert top_name == "Kensington and Chelsea", (
        f"Expected Kensington and Chelsea most expensive, got {top_name}"
    )


def test_5yr_avg_present_for_all(housing_data: dict) -> None:
    """5-year average should be present for every borough — used as fallback context."""
    for code, b in housing_data["boroughs"].items():
        assert b.get("ratio_5yr_avg") is not None, (
            f"{b['name']} missing 5yr average"
        )


def test_loader_function() -> None:
    """The API loader function should produce the response shape consumed by the frontend."""
    if not DATA_PATH.exists():
        pytest.skip("Housing affordability data not generated")
    try:
        from api.routers.boroughs import _load_housing_data
    except ModuleNotFoundError as exc:
        pytest.skip(f"API deps not installed locally ({exc.name}); run on server / in CI")
    _load_housing_data.cache_clear()
    rows = _load_housing_data()
    assert len(rows) == 33
    assert all("borough_code" in r and "borough_name" in r for r in rows)
    assert all("ratio" in r for r in rows)
    assert all(r["year"] is not None for r in rows)
