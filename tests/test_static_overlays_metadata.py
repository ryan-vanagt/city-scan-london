"""Vintage / metadata assertions on the static-JSON overlays.

The four overlay datasets (deprivation, housing affordability, ONS Health
Index, TfL PTAL) all carry vintage years that the agent system prompt,
captions, and footer attributions reference. If the file ships without a
year — or with a year that diverges from the documented vintage — the
agent and UI will silently quote a stale or missing year. These tests
fail fast on that drift.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC = REPO_ROOT / "data" / "static"


def _load(name: str) -> dict:
    path = STATIC / name
    if not path.exists():
        pytest.skip(f"{name} not present — run the corresponding fetch script first")
    return json.loads(path.read_text(encoding="utf-8"))


def test_imd_metadata_vintage():
    data = _load("imd_borough.json")
    meta = data.get("_metadata", {})
    source = str(meta.get("source", ""))
    published = str(meta.get("published", ""))
    assert any(token in source + published for token in ("2025", "2019", "2015")), (
        "IMD JSON metadata must encode the publication vintage (source or published)"
    )


def test_housing_affordability_metadata_year():
    data = _load("housing_affordability.json")
    meta = data.get("_metadata", {})
    year = meta.get("year")
    assert isinstance(year, int), "housing_affordability metadata must include integer year"
    assert 2020 <= year <= 2030, f"housing_affordability year out of expected window: {year}"


def test_ons_health_index_metadata_year():
    data = _load("ons_health_index.json")
    meta = data.get("_metadata", {})
    # Health Index can carry latest_year, year, or score_year_range
    has_year = any(
        k in meta for k in ("latest_year", "year", "year_range", "score_year_range")
    )
    assert has_year, "ons_health_index metadata must encode the score year"


def test_transit_access_metadata_vintage_2015():
    data = _load("transit_access.json")
    meta = data.get("_metadata", {})
    vintage = meta.get("vintage") or ""
    assert "2015" in str(vintage), (
        "PTAL is republished only on TfL network changes; the current "
        "borough-average edition is 2015. If this fails because TfL has "
        "released a new edition, update the system prompt's Elizabeth "
        "Line caveat in the same change."
    )


def test_score_quality_metadata_describes_method():
    data = _load("score_quality.json")
    meta = data.get("_metadata", {})
    method = meta.get("method", "")
    assert "bootstrap" in method.lower(), "score_quality metadata.method must describe the bootstrap"
    assert meta.get("bootstrap_resamples"), "score_quality metadata must record resample count"
    assert meta.get("trend_window_days"), "score_quality metadata must record trend window"
