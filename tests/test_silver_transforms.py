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

def _validate_rows(rows: list[tuple], source_name: str, expected_metric: str) -> None:
    """Raise AssertionError if any invariant is violated."""
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
    assert metrics == {expected_metric}, f"{source_name}: metric_name — got {metrics}"

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
    ("green_space", _transform_green_space, "green_space"),
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
