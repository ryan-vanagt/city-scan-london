"""Test pipeline/gold.py — aggregation with real silver data + deterministic edge cases."""

from pathlib import Path
from statistics import mean

import pytest

from pipeline.schemas import BOROUGHS
from pipeline.gold import aggregate, _load_weights
from pipeline.silver import transform_all, load as silver_load

from conftest import insert_silver

# ---------------------------------------------------------------------------
# Module-level skip: real-data tests require bronze data
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


# ---------------------------------------------------------------------------
# Real data: bronze → silver → gold
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def real_gold_data(tmp_path_factory):
    """Run the full silver→gold pipeline once; return (gold_rows, silver_rows)."""
    if not _bronze_data_exists():
        pytest.skip("no bronze data — run `python ingestion/run_pipeline.py` first")

    import duckdb
    from pipeline.schemas import init_db

    con = duckdb.connect(":memory:")
    init_db(con)
    silver_rows = transform_all()
    silver_load(con, silver_rows)
    aggregate(con)
    gold_data = con.execute("SELECT * FROM gold_scores ORDER BY borough_code").fetchall()
    con.close()
    return gold_data, silver_rows


def test_silver_transform_all_produces_rows(real_gold_data):
    _, silver_rows = real_gold_data
    assert len(silver_rows) > 0, f"transform_all() returned {len(silver_rows)} rows"


def test_aggregate_inserts_rows(real_gold_data):
    gold_data, _ = real_gold_data
    assert len(gold_data) > 0


def test_all_borough_codes_valid(real_gold_data):
    gold_data, _ = real_gold_data
    bad = [row[0] for row in gold_data if row[0] not in BOROUGHS]
    assert len(bad) == 0, f"unknown borough codes: {bad}"


def test_names_match_codes(real_gold_data):
    gold_data, _ = real_gold_data
    mismatches = [
        (row[0], row[1]) for row in gold_data
        if BOROUGHS[row[0]]["name"] != row[1]
    ]
    assert len(mismatches) == 0, f"name/code mismatches: {mismatches}"


def test_no_null_composite_scores(real_gold_data):
    gold_data, _ = real_gold_data
    composites = [row[7] for row in gold_data]
    assert all(c is not None for c in composites)


def test_all_composites_in_range(real_gold_data):
    gold_data, _ = real_gold_data
    composites = [row[7] for row in gold_data]
    assert all(0 <= c <= 100 for c in composites), \
        f"range: [{min(composites)}, {max(composites)}]"


def test_all_sub_scores_null_or_in_range(real_gold_data):
    gold_data, _ = real_gold_data
    for row in gold_data:
        bc = row[0]
        for label, val in [("air", row[3]), ("transit", row[4]),
                            ("sentiment", row[5]), ("immune", row[6])]:
            assert val is None or 0 <= val <= 100, \
                f"{bc} {label}={val} out of [0, 100]"


def test_transit_coverage_is_26(real_gold_data):
    gold_data, _ = real_gold_data
    has_transit = sum(1 for r in gold_data if r[4] is not None)
    assert has_transit == 26, f"expected 26 transit-covered boroughs, got {has_transit}"


def test_sentiment_coverage_is_33(real_gold_data):
    gold_data, _ = real_gold_data
    has_sentiment = sum(1 for r in gold_data if r[5] is not None)
    assert has_sentiment == 33, f"expected 33 sentiment-covered boroughs, got {has_sentiment}"


def test_air_coverage_at_least_10(real_gold_data):
    gold_data, _ = real_gold_data
    has_air = sum(1 for r in gold_data if r[3] is not None)
    assert has_air >= 10, f"expected >= 10 air-covered boroughs, got {has_air}"


def test_immune_coverage_at_least_30(real_gold_data):
    gold_data, _ = real_gold_data
    has_immune = sum(1 for r in gold_data if r[6] is not None)
    assert has_immune >= 30, f"expected >= 30 immune-covered boroughs, got {has_immune}"


def test_composite_equals_weighted_avg_of_sub_scores(real_gold_data):
    gold_data, _ = real_gold_data
    weights = _load_weights()
    for row in gold_data:
        bc = row[0]
        air, transit, sentiment, immune, composite = (
            row[3], row[4], row[5], row[6], row[7]
        )
        pairs = [(air, weights[0]), (transit, weights[1]),
                 (sentiment, weights[2]), (immune, weights[3])]
        present = [(s, w) for s, w in pairs if s is not None]
        expected = sum(s * w for s, w in present) / sum(w for _, w in present)
        assert abs(composite - round(expected, 2)) <= 0.01, \
            f"{bc}: expected composite {expected:.2f}, got {composite}"


def test_tube_transit_coverage_correct(real_gold_data):
    gold_data, _ = real_gold_data
    NO_TUBE = {"E09000004", "E09000006", "E09000008", "E09000012",
               "E09000021", "E09000023", "E09000029"}
    for row in gold_data:
        bc, transit = row[0], row[4]
        if bc in NO_TUBE:
            assert transit is None, \
                f"{bc} ({BOROUGHS[bc]['name']}) should have NULL transit, got {transit}"
        else:
            assert transit is not None, \
                f"{bc} ({BOROUGHS[bc]['name']}) should have non-NULL transit"


def test_sentiment_equals_avg_across_sources(real_gold_data):
    gold_data, silver_rows = real_gold_data
    sentiment_by_borough: dict[str, list[float]] = {}
    for srow in silver_rows:
        if srow[3] == "sentiment":
            bc = srow[0]
            sentiment_by_borough.setdefault(bc, []).append(srow[5])

    for row in gold_data:
        bc, sentiment = row[0], row[5]
        if bc in sentiment_by_borough and sentiment is not None:
            expected_avg = mean(sentiment_by_borough[bc])
            assert abs(sentiment - expected_avg) <= 0.01, \
                f"{bc}: expected sentiment {expected_avg:.2f}, got {sentiment}"


def test_no_duplicate_boroughs_in_gold(real_gold_data):
    gold_data, _ = real_gold_data
    gold_codes = [row[0] for row in gold_data]
    assert len(gold_codes) == len(set(gold_codes)), \
        f"{len(gold_codes)} rows but only {len(set(gold_codes))} unique codes"


# ---------------------------------------------------------------------------
# Deterministic edge cases (synthetic data, no bronze required)
# ---------------------------------------------------------------------------

def test_empty_silver_produces_zero_gold_rows(fresh_db):
    rows = aggregate(fresh_db)
    assert rows == 0


def test_custom_weights_composite_calculation(fresh_db, monkeypatch):
    BC1 = "E09000001"
    insert_silver(fresh_db, BC1, "air_quality", 100.0, source="openaq")
    insert_silver(fresh_db, BC1, "transit",     0.0,   source="tfl")
    insert_silver(fresh_db, BC1, "sentiment",   0.0,   source="reddit")
    insert_silver(fresh_db, BC1, "crime",       0.0,   source="met_police")

    monkeypatch.setenv("SCORE_WEIGHTS", "0.7,0.1,0.1,0.1")
    _load_weights.cache_clear()
    try:
        aggregate(fresh_db)
        gold = fresh_db.execute(
            "SELECT composite_score FROM gold_scores WHERE borough_code = ?", [BC1]
        ).fetchone()
        assert gold is not None
        assert abs(gold[0] - 70.0) < 0.01, f"expected 70.0, got {gold[0]}"
    finally:
        _load_weights.cache_clear()


def test_invalid_weights_fall_back_to_defaults(monkeypatch):
    monkeypatch.setenv("SCORE_WEIGHTS", "not,valid,weights")
    _load_weights.cache_clear()
    try:
        w = _load_weights()
        assert w == (0.25, 0.25, 0.25, 0.25), f"expected default weights, got {w}"
    finally:
        _load_weights.cache_clear()


def test_ddl_rejects_null_composite(fresh_db):
    with pytest.raises(Exception):
        fresh_db.execute(
            "INSERT INTO gold_scores VALUES "
            "('E09000001','Test','2026-01-01T00:00:00+00',80,90,70,60,NULL,'2026-01-01T00:00:00+00','gold')"
        )
