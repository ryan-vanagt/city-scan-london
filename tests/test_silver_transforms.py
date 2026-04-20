"""Test pipeline/silver.py — all 7 source transformers + transform_all() + load()."""

from pathlib import Path

import duckdb
import pytest

from pipeline.schemas import BOROUGHS, init_db
from pipeline.silver import (
    _load_bronze,
    _transform_bbc,
    _transform_green_space,
    _transform_guardian,
    _transform_laei,
    _transform_met_police,
    _transform_nhs_ae,
    _transform_openaq,
    _transform_reddit,
    _transform_tfl,
    load,
    transform_all,
)

# ---------------------------------------------------------------------------
# Module-level skip: requires bronze data on disk
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_BRONZE_ROOT = _PROJECT_ROOT / "data" / "bronze"


def _bronze_data_exists() -> bool:
    if not _BRONZE_ROOT.exists():
        return False
    return any(
        f.suffix == ".json"
        for d in _BRONZE_ROOT.iterdir() if d.is_dir()
        for f in d.iterdir()
    )


pytestmark = pytest.mark.skipif(
    not _bronze_data_exists(),
    reason="no bronze data on disk — run `python ingestion/run_pipeline.py` first",
)


@pytest.fixture(scope="module")
def silver_rows():
    """Compute transform_all() once for the entire module (loads sentiment model)."""
    return transform_all()

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _validate_rows(rows: list[tuple], source_name: str, expected_metric) -> None:
    """Raise AssertionError if any invariant is violated.

    expected_metric may be a single string or a set of strings (for sources
    that emit multiple metric rows per borough, like green_space which emits
    both raw coverage and access-weighted variants).
    """
    assert len(rows) > 0, f"{source_name}: empty result"

    for row in rows:
        borough_code = row[0]
        borough_name = row[1]
        normalised_score = row[5]

        assert borough_code in BOROUGHS, f"{source_name}: invalid borough_code {borough_code}"
        assert BOROUGHS[borough_code]["name"] == borough_name, (
            f"{source_name}: name mismatch for {borough_code}: "
            f"expected {BOROUGHS[borough_code]['name']}, got {borough_name}"
        )
        assert 0 <= normalised_score <= 100, (
            f"{source_name}: score {normalised_score} out of [0, 100]"
        )

    metrics = {r[3] for r in rows}
    expected_set = expected_metric if isinstance(expected_metric, set) else {expected_metric}
    assert metrics == expected_set, f"{source_name}: metric_name — got {metrics}, expected {expected_set}"

    sources = {r[6] for r in rows}
    assert sources == {source_name}, f"{source_name}: source tag — got {sources}"


# ---------------------------------------------------------------------------
# Source fixture map
# ---------------------------------------------------------------------------

SOURCES = [
    ("nhs_ae",      _transform_nhs_ae,      "nhs_ae"),
    ("tfl",         _transform_tfl,         "transit"),
    ("met_police",  _transform_met_police,  "crime"),
    ("openaq",      _transform_openaq,      "air_quality"),
    ("green_space", _transform_green_space, {"green_space", "green_space_access"}),
    ("laei",        _transform_laei,        "air_quality_modelled"),
    ("reddit",      _transform_reddit,      "sentiment"),
    ("bbc",         _transform_bbc,         "sentiment"),
    ("guardian",    _transform_guardian,    "sentiment"),
]

SOURCE_IDS = [s[0] for s in SOURCES]

# ---------------------------------------------------------------------------
# Individual transformer tests — all invariants at once per source
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("source_name,transformer,expected_metric", SOURCES, ids=SOURCE_IDS)
def test_transformer_invariants(source_name, transformer, expected_metric):
    loaded = _load_bronze(source_name)
    if loaded is None:
        pytest.skip(f"{source_name}: no bronze data")
    data, timestamp = loaded
    rows = transformer(data, timestamp)
    _validate_rows(rows, source_name, expected_metric)


# ---------------------------------------------------------------------------
# Borough coverage
# ---------------------------------------------------------------------------

EXPECTED_COVERAGE = {
    "nhs_ae":      ("exact", 33),
    "tfl":         ("exact", 26),
    "met_police":  ("exact", 33),
    "openaq":      ("min",   15),
    "green_space": ("exact", 33),
    "laei":        ("exact", 33),
    "reddit":      ("exact", 33),
    "bbc":         ("exact", 33),
    "guardian":    ("exact", 33),
}


@pytest.mark.parametrize("source_name,transformer,_", SOURCES, ids=SOURCE_IDS)
def test_borough_coverage(source_name, transformer, _):
    loaded = _load_bronze(source_name)
    if loaded is None:
        pytest.skip(f"{source_name}: no bronze data")
    data, timestamp = loaded
    rows = transformer(data, timestamp)
    unique_boroughs = len({r[0] for r in rows})

    mode, count = EXPECTED_COVERAGE[source_name]
    if mode == "exact":
        assert unique_boroughs == count, (
            f"{source_name}: expected exactly {count} boroughs, got {unique_boroughs}"
        )
    else:
        assert unique_boroughs >= count, (
            f"{source_name}: expected >= {count} boroughs, got {unique_boroughs}"
        )


# ---------------------------------------------------------------------------
# Full transform_all() + load() into DuckDB
# ---------------------------------------------------------------------------

def test_transform_all_returns_rows(silver_rows):
    assert len(silver_rows) > 0, f"transform_all() returned {len(silver_rows)} rows"


def test_load_inserts_all_rows(silver_rows):
    con = duckdb.connect(":memory:")
    init_db(con)
    total_rows = load(con, silver_rows)
    con.close()
    assert total_rows == len(silver_rows), f"inserted {total_rows} of {len(silver_rows)}"


@pytest.mark.parametrize("col", [
    "borough_code", "borough_name", "timestamp",
    "metric_name", "normalised_score", "source",
])
def test_no_nulls_in_not_null_columns(silver_rows, col):
    con = duckdb.connect(":memory:")
    init_db(con)
    load(con, silver_rows)
    nulls = con.execute(
        f"SELECT COUNT(*) FROM silver_metrics WHERE {col} IS NULL"
    ).fetchone()[0]
    con.close()
    assert nulls == 0, f"{nulls} NULLs found in {col}"


def test_no_orphan_borough_codes_in_db(silver_rows):
    con = duckdb.connect(":memory:")
    init_db(con)
    load(con, silver_rows)
    orphans = con.execute("""
        SELECT DISTINCT borough_code FROM silver_metrics
        WHERE borough_code NOT IN (SELECT unnest(?::VARCHAR[]))
    """, [list(BOROUGHS.keys())]).fetchall()
    con.close()
    assert len(orphans) == 0, f"orphan borough codes: {orphans}"


def test_db_scores_in_range(silver_rows):
    con = duckdb.connect(":memory:")
    init_db(con)
    load(con, silver_rows)
    r = con.execute(
        "SELECT MIN(normalised_score), MAX(normalised_score) FROM silver_metrics"
    ).fetchone()
    con.close()
    assert r[0] >= 0 and r[1] <= 100, f"scores out of range: [{r[0]}, {r[1]}]"


# ---------------------------------------------------------------------------
# Green-space access-weighted aggregation (Task 1 addition)
# ---------------------------------------------------------------------------

def _green_bronze(borough_rows, ward_rows):
    """Helper: construct a bronze-shaped green_space payload."""
    return {
        "results": borough_rows,
        "wards": ward_rows,
        "fetched_at": "2026-04-19T20:00:00+00:00",
    }


def test_access_weighted_green_formula_correct(monkeypatch):
    """Weighted mean: (80×1000 + 20×9000) / 10000 = 26.0"""
    from pipeline import silver as silver_mod

    # Stub ward populations: two wards in one borough, one high/low ratio
    monkeypatch.setattr(silver_mod, "_ward_pops_cache", {"W1": 1000, "W2": 9000})

    payload = _green_bronze(
        borough_rows=[{"borough_code": "E09000001", "green_pct": 50.0}],
        ward_rows=[
            {"ward_code": "W1", "borough_code": "E09000001", "green_pct": 80.0},
            {"ward_code": "W2", "borough_code": "E09000001", "green_pct": 20.0},
        ],
    )
    rows = silver_mod._transform_green_space(payload, "2026-04-19T20:00:00+00:00")

    # Expect both metrics
    by_metric = {r[3]: r for r in rows}
    assert "green_space" in by_metric
    assert "green_space_access" in by_metric
    # Raw stays at 50.0
    assert by_metric["green_space"][4] == 50.0
    # Access-weighted = (80*1000 + 20*9000) / 10000 = 26.0
    assert abs(by_metric["green_space_access"][4] - 26.0) < 0.01, \
        f"expected 26.0, got {by_metric['green_space_access'][4]}"


def test_access_weighted_green_falls_back_when_no_ward_pop(monkeypatch):
    """Zero ward population coverage -> access-weighted uses raw borough %."""
    from pipeline import silver as silver_mod

    monkeypatch.setattr(silver_mod, "_ward_pops_cache", {})  # empty → no matches

    payload = _green_bronze(
        borough_rows=[{"borough_code": "E09000001", "green_pct": 42.0}],
        ward_rows=[
            {"ward_code": "W_UNKNOWN", "borough_code": "E09000001", "green_pct": 10.0},
        ],
    )
    rows = silver_mod._transform_green_space(payload, "2026-04-19T20:00:00+00:00")

    by_metric = {r[3]: r for r in rows}
    # Access-weighted should fall back to the raw borough value
    assert by_metric["green_space_access"][4] == 42.0, \
        f"expected fallback to 42.0, got {by_metric['green_space_access'][4]}"


def test_laei_both_pollutants_use_weighted_who_ratio():
    """LAEI transform: when both PM2.5 + NO2 present, use 60/40 weighted ratio."""
    from pipeline.silver import _transform_laei
    payload = {
        "results": [
            {"borough_code": "E09000001", "borough_name": "City of London",
             "pm25": 10.82, "no2": 30.19},
            {"borough_code": "E09000016", "borough_name": "Havering",
             "pm25": 8.10, "no2": 16.20},
        ],
    }
    rows = _transform_laei(payload, "2026-04-20T12:00:00+00:00")
    assert len(rows) == 2
    # Both metrics rows tagged consistently
    assert {r[3] for r in rows} == {"air_quality_modelled"}
    assert {r[6] for r in rows} == {"laei"}
    # Verify the WHO-ratio decay: Havering should score higher than City of London
    # (lower pollution = higher score)
    by_borough = {r[0]: r[5] for r in rows}
    assert by_borough["E09000016"] > by_borough["E09000001"], \
        f"Havering ({by_borough['E09000016']}) should score higher than City of London ({by_borough['E09000001']})"
    # Both scores within [0, 100]
    assert all(0 <= r[5] <= 100 for r in rows)
    # raw_value should be the PM2.5 value (PM2.5 takes precedence)
    city_raw = next(r[4] for r in rows if r[0] == "E09000001")
    assert abs(city_raw - 10.82) < 0.01


def test_laei_missing_pollutant_falls_back_to_the_other():
    """LAEI transform: when only one pollutant is present, use its own WHO ratio."""
    from pipeline.silver import _transform_laei
    payload = {
        "results": [
            {"borough_code": "E09000001", "borough_name": "City of London",
             "pm25": 10.0, "no2": None},
            {"borough_code": "E09000016", "borough_name": "Havering",
             "pm25": None, "no2": 25.0},
        ],
    }
    rows = _transform_laei(payload, "2026-04-20T12:00:00+00:00")
    assert len(rows) == 2
    # PM2.5-only row: raw = PM2.5
    pm_row = next(r for r in rows if r[0] == "E09000001")
    assert abs(pm_row[4] - 10.0) < 0.01
    # NO2-only row: raw = NO2
    no2_row = next(r for r in rows if r[0] == "E09000016")
    assert abs(no2_row[4] - 25.0) < 0.01


def test_access_weighted_green_excludes_unknown_wards(monkeypatch):
    """Wards without population data are excluded from num + denom, not zeroed."""
    from pipeline import silver as silver_mod

    # Only W1 has population data
    monkeypatch.setattr(silver_mod, "_ward_pops_cache", {"W1": 5000})

    payload = _green_bronze(
        borough_rows=[{"borough_code": "E09000001", "green_pct": 30.0}],
        ward_rows=[
            {"ward_code": "W1",         "borough_code": "E09000001", "green_pct": 60.0},
            {"ward_code": "W_UNKNOWN",  "borough_code": "E09000001", "green_pct": 0.0},
        ],
    )
    rows = silver_mod._transform_green_space(payload, "2026-04-19T20:00:00+00:00")
    by_metric = {r[3]: r for r in rows}
    # W_UNKNOWN is dropped; access-weighted = 60.0 (from W1 alone), not diluted
    assert by_metric["green_space_access"][4] == 60.0, \
        f"expected 60.0, got {by_metric['green_space_access'][4]}"
