"""Test agents/tools/ — curated tools + run_sql with guardrails.

Tests both against real gold data (requires prior pipeline run) and
deterministic edge cases using in-memory DuckDB with synthetic data.
"""

import duckdb
import pytest

from agents.tools.borough_query import (
    _VALID_METRICS,
    _resolve_borough,
    compare_boroughs,
    get_borough_health,
)
from agents.tools.health_score import _avg, get_london_score
from agents.tools.sql_query import run_sql
from agents.tools.trend_analysis import get_trend


# ---------------------------------------------------------------------------
# Helper — plain function, not a fixture (tests call it directly)
# ---------------------------------------------------------------------------

def insert_gold(
    con: duckdb.DuckDBPyConnection,
    borough_code: str,
    borough_name: str,
    air: float | None = None,
    transit: float | None = None,
    sentiment: float | None = None,
    immune: float | None = None,
    composite: float = 50.0,
    timestamp: str = "2026-04-09T12:00:00+00:00",
    ingested_at: str = "2026-04-09T12:00:00+00:00",
) -> None:
    """Insert a single gold_scores row for testing."""
    con.execute(
        """
        INSERT INTO gold_scores
        (borough_code, borough_name, timestamp, air_score, transit_score,
         sentiment_score, immune_score, composite_score, ingested_at, pipeline_stage)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            borough_code, borough_name, timestamp, air, transit,
            sentiment, immune, composite, ingested_at, "gold",
        ],
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_with_one_borough(fresh_db):
    """fresh_db pre-populated with a single Camden row."""
    insert_gold(fresh_db, "E09000007", "Camden")
    return fresh_db


@pytest.fixture
def db_with_camden_full(fresh_db):
    """fresh_db with a fully-scored Camden row."""
    insert_gold(
        fresh_db, "E09000007", "Camden",
        air=34.2, transit=82.0, sentiment=61.5, immune=55.6, composite=58.3,
    )
    return fresh_db


@pytest.fixture
def db_with_three_boroughs(fresh_db):
    """fresh_db with Camden, City of London, and Brent rows."""
    insert_gold(fresh_db, "E09000007", "Camden", air=30.0, composite=50.0)
    insert_gold(fresh_db, "E09000001", "City of London", air=80.0, composite=75.0)
    insert_gold(fresh_db, "E09000005", "Brent", air=60.0, composite=60.0)
    return fresh_db


@pytest.fixture
def db_with_two_boroughs(fresh_db):
    """fresh_db with Camden and City of London (with all sub-scores)."""
    insert_gold(
        fresh_db, "E09000007", "Camden",
        air=40.0, transit=60.0, sentiment=80.0, immune=50.0, composite=57.5,
    )
    insert_gold(
        fresh_db, "E09000001", "City of London",
        air=60.0, transit=80.0, sentiment=70.0, immune=90.0, composite=75.0,
    )
    return fresh_db


@pytest.fixture
def db_with_trend_data(fresh_db):
    """fresh_db with three Camden rows spanning different timestamps."""
    insert_gold(
        fresh_db, "E09000007", "Camden", composite=50.0,
        timestamp="2026-04-07T12:00:00+00:00",
        ingested_at="2026-04-07T12:00:00+00:00",
    )
    insert_gold(
        fresh_db, "E09000007", "Camden", composite=55.0,
        timestamp="2026-04-08T12:00:00+00:00",
        ingested_at="2026-04-08T12:00:00+00:00",
    )
    insert_gold(
        fresh_db, "E09000007", "Camden", composite=60.0,
        timestamp="2026-04-09T12:00:00+00:00",
        ingested_at="2026-04-09T12:00:00+00:00",
    )
    return fresh_db


@pytest.fixture
def db_with_sql_data(fresh_db):
    """fresh_db with Camden and City of London rows for run_sql tests."""
    insert_gold(
        fresh_db, "E09000007", "Camden",
        air=34.0, transit=82.0, sentiment=61.0, immune=55.0, composite=58.0,
    )
    insert_gold(
        fresh_db, "E09000001", "City of London",
        air=80.0, transit=90.0, sentiment=70.0, immune=85.0, composite=81.0,
    )
    return fresh_db


# ===========================================================================
# _avg helper
# ===========================================================================

def test_avg_normal_list():
    assert _avg([10.0, 20.0, 30.0]) == 20.0


def test_avg_with_nones():
    assert _avg([10.0, None, 30.0]) == 20.0


def test_avg_all_none():
    assert _avg([None, None]) is None


def test_avg_empty_list():
    assert _avg([]) is None


def test_avg_single_value():
    assert _avg([42.0]) == 42.0


# ===========================================================================
# _resolve_borough (synthetic)
# ===========================================================================

def test_resolve_by_name_lowercase(db_with_one_borough):
    assert _resolve_borough("camden", db_with_one_borough) == ("E09000007", "Camden")


def test_resolve_by_name_mixed_case(db_with_one_borough):
    assert _resolve_borough("Camden", db_with_one_borough) == ("E09000007", "Camden")


def test_resolve_by_ons_code(db_with_one_borough):
    assert _resolve_borough("E09000007", db_with_one_borough) == ("E09000007", "Camden")


def test_resolve_not_found(db_with_one_borough):
    assert _resolve_borough("Atlantis", db_with_one_borough) is None


def test_resolve_empty_string(db_with_one_borough):
    assert _resolve_borough("", db_with_one_borough) is None


def test_resolve_whitespace(db_with_one_borough):
    assert _resolve_borough("   ", db_with_one_borough) is None


# ===========================================================================
# get_borough_health (synthetic)
# ===========================================================================

def test_get_borough_health_found(db_with_camden_full):
    result = get_borough_health("Camden", con=db_with_camden_full)
    assert result["found"] is True


def test_get_borough_health_borough_code(db_with_camden_full):
    result = get_borough_health("Camden", con=db_with_camden_full)
    assert result["borough_code"] == "E09000007"


def test_get_borough_health_borough_name(db_with_camden_full):
    result = get_borough_health("Camden", con=db_with_camden_full)
    assert result["borough_name"] == "Camden"


def test_get_borough_health_composite(db_with_camden_full):
    result = get_borough_health("Camden", con=db_with_camden_full)
    assert result["composite_score"] == pytest.approx(58.3)


def test_get_borough_health_air(db_with_camden_full):
    result = get_borough_health("Camden", con=db_with_camden_full)
    assert result["air_score"] == pytest.approx(34.2)


def test_get_borough_health_transit(db_with_camden_full):
    result = get_borough_health("Camden", con=db_with_camden_full)
    assert result["transit_score"] == pytest.approx(82.0)


def test_get_borough_health_has_timestamp(db_with_camden_full):
    result = get_borough_health("Camden", con=db_with_camden_full)
    assert result["timestamp"] is not None


def test_get_borough_health_not_found_flag(db_with_camden_full):
    result = get_borough_health("NotABorough", con=db_with_camden_full)
    assert result["found"] is False


def test_get_borough_health_not_found_all_none(db_with_camden_full):
    result = get_borough_health("NotABorough", con=db_with_camden_full)
    none_fields = [
        "borough_code", "borough_name", "timestamp",
        "air_score", "transit_score", "sentiment_score",
        "immune_score", "composite_score",
    ]
    assert all(result[k] is None for k in none_fields)


def test_get_borough_health_by_ons_code(db_with_camden_full):
    result = get_borough_health("E09000007", con=db_with_camden_full)
    assert result["found"] is True
    assert result["borough_name"] == "Camden"


def test_get_borough_health_latest_row_wins(fresh_db):
    insert_gold(
        fresh_db, "E09000007", "Camden",
        air=34.2, transit=82.0, sentiment=61.5, immune=55.6, composite=58.3,
    )
    insert_gold(
        fresh_db, "E09000007", "Camden",
        air=99.0, transit=99.0, sentiment=99.0, immune=99.0, composite=99.0,
        ingested_at="2026-04-10T12:00:00+00:00",
    )
    result = get_borough_health("Camden", con=fresh_db)
    assert result["composite_score"] == pytest.approx(99.0)


# ===========================================================================
# compare_boroughs (synthetic)
# ===========================================================================

def test_compare_boroughs_best_first_order_field(db_with_three_boroughs):
    result = compare_boroughs("air_score", top_n=3, ascending=False, con=db_with_three_boroughs)
    assert result["order"] == "best_first"


def test_compare_boroughs_best_first_top_borough(db_with_three_boroughs):
    result = compare_boroughs("air_score", top_n=3, ascending=False, con=db_with_three_boroughs)
    assert result["boroughs"][0]["borough_name"] == "City of London"


def test_compare_boroughs_best_first_rank_numbers(db_with_three_boroughs):
    result = compare_boroughs("air_score", top_n=3, ascending=False, con=db_with_three_boroughs)
    assert [b["rank"] for b in result["boroughs"]] == [1, 2, 3]


def test_compare_boroughs_worst_first_order_field(db_with_three_boroughs):
    result = compare_boroughs("air_score", top_n=2, ascending=True, con=db_with_three_boroughs)
    assert result["order"] == "worst_first"


def test_compare_boroughs_worst_first_top_borough(db_with_three_boroughs):
    result = compare_boroughs("air_score", top_n=2, ascending=True, con=db_with_three_boroughs)
    assert result["boroughs"][0]["borough_name"] == "Camden"


def test_compare_boroughs_worst_first_respects_top_n(db_with_three_boroughs):
    result = compare_boroughs("air_score", top_n=2, ascending=True, con=db_with_three_boroughs)
    assert len(result["boroughs"]) == 2


def test_compare_boroughs_invalid_metric(db_with_three_boroughs):
    result = compare_boroughs("fake_metric", con=db_with_three_boroughs)
    assert result["boroughs"] == []


def test_compare_boroughs_top_n_clamped_to_max(db_with_three_boroughs):
    result = compare_boroughs("composite_score", top_n=100, con=db_with_three_boroughs)
    assert len(result["boroughs"]) <= 33


def test_compare_boroughs_top_n_clamped_to_min(db_with_three_boroughs):
    result = compare_boroughs("composite_score", top_n=-5, con=db_with_three_boroughs)
    assert len(result["boroughs"]) >= 1


def test_compare_boroughs_nulls_last(fresh_db):
    insert_gold(fresh_db, "E09000007", "Camden", air=30.0, composite=50.0)
    insert_gold(fresh_db, "E09000001", "City of London", air=80.0, composite=75.0)
    insert_gold(fresh_db, "E09000005", "Brent", air=60.0, composite=60.0)
    insert_gold(fresh_db, "E09000012", "Hackney", air=None, composite=65.0)
    result = compare_boroughs("air_score", top_n=4, ascending=False, con=fresh_db)
    assert result["boroughs"][-1]["borough_name"] == "Hackney"


# ===========================================================================
# get_london_score (synthetic)
# ===========================================================================

def test_get_london_score_borough_count(db_with_two_boroughs):
    result = get_london_score(con=db_with_two_boroughs)
    assert result["borough_count"] == 2


def test_get_london_score_composite(db_with_two_boroughs):
    result = get_london_score(con=db_with_two_boroughs)
    assert result["composite_score"] == pytest.approx(66.25)


def test_get_london_score_air(db_with_two_boroughs):
    result = get_london_score(con=db_with_two_boroughs)
    assert result["air_score"] == pytest.approx(50.0)


def test_get_london_score_transit(db_with_two_boroughs):
    result = get_london_score(con=db_with_two_boroughs)
    assert result["transit_score"] == pytest.approx(70.0)


def test_get_london_score_has_timestamp(db_with_two_boroughs):
    result = get_london_score(con=db_with_two_boroughs)
    assert result["timestamp"] is not None


def test_get_london_score_empty_db_borough_count(fresh_db):
    result = get_london_score(con=fresh_db)
    assert result["borough_count"] == 0


def test_get_london_score_empty_db_composite_none(fresh_db):
    result = get_london_score(con=fresh_db)
    assert result["composite_score"] is None


# ===========================================================================
# get_trend (synthetic)
# ===========================================================================

def test_get_trend_found(db_with_trend_data):
    result = get_trend("Camden", "composite_score", 7, con=db_with_trend_data)
    assert result["found"] is True


def test_get_trend_borough_code(db_with_trend_data):
    result = get_trend("Camden", "composite_score", 7, con=db_with_trend_data)
    assert result["borough_code"] == "E09000007"


def test_get_trend_data_points(db_with_trend_data):
    result = get_trend("Camden", "composite_score", 7, con=db_with_trend_data)
    assert result["data_points"] == 3


def test_get_trend_direction_improving(db_with_trend_data):
    result = get_trend("Camden", "composite_score", 7, con=db_with_trend_data)
    assert result["direction"] == "improving"


def test_get_trend_delta_improving(db_with_trend_data):
    result = get_trend("Camden", "composite_score", 7, con=db_with_trend_data)
    assert result["delta"] == pytest.approx(10.0)


def test_get_trend_chronological_order(db_with_trend_data):
    result = get_trend("Camden", "composite_score", 7, con=db_with_trend_data)
    assert result["trend"][0]["score"] == pytest.approx(50.0)
    assert result["trend"][-1]["score"] == pytest.approx(60.0)


def test_get_trend_direction_declining(fresh_db):
    insert_gold(
        fresh_db, "E09000007", "Camden", composite=80.0,
        timestamp="2026-04-07T12:00:00+00:00",
        ingested_at="2026-04-07T12:00:00+00:00",
    )
    insert_gold(
        fresh_db, "E09000007", "Camden", composite=70.0,
        timestamp="2026-04-09T12:00:00+00:00",
        ingested_at="2026-04-09T12:00:00+00:00",
    )
    result = get_trend("Camden", "composite_score", 7, con=fresh_db)
    assert result["direction"] == "declining"


def test_get_trend_delta_declining(fresh_db):
    insert_gold(
        fresh_db, "E09000007", "Camden", composite=80.0,
        timestamp="2026-04-07T12:00:00+00:00",
        ingested_at="2026-04-07T12:00:00+00:00",
    )
    insert_gold(
        fresh_db, "E09000007", "Camden", composite=70.0,
        timestamp="2026-04-09T12:00:00+00:00",
        ingested_at="2026-04-09T12:00:00+00:00",
    )
    result = get_trend("Camden", "composite_score", 7, con=fresh_db)
    assert result["delta"] == pytest.approx(-10.0)


def test_get_trend_direction_stable(fresh_db):
    insert_gold(
        fresh_db, "E09000007", "Camden", composite=50.0,
        timestamp="2026-04-07T12:00:00+00:00",
        ingested_at="2026-04-07T12:00:00+00:00",
    )
    insert_gold(
        fresh_db, "E09000007", "Camden", composite=51.5,
        timestamp="2026-04-09T12:00:00+00:00",
        ingested_at="2026-04-09T12:00:00+00:00",
    )
    result = get_trend("Camden", "composite_score", 7, con=fresh_db)
    assert result["direction"] == "stable"


def test_get_trend_single_point_direction_none(fresh_db):
    insert_gold(fresh_db, "E09000007", "Camden", composite=50.0)
    result = get_trend("Camden", "composite_score", 7, con=fresh_db)
    assert result["direction"] is None


def test_get_trend_single_point_delta_none(fresh_db):
    insert_gold(fresh_db, "E09000007", "Camden", composite=50.0)
    result = get_trend("Camden", "composite_score", 7, con=fresh_db)
    assert result["delta"] is None


def test_get_trend_not_found(db_with_trend_data):
    result = get_trend("Atlantis", "composite_score", 7, con=db_with_trend_data)
    assert result["found"] is False


def test_get_trend_not_found_empty_trend_list(db_with_trend_data):
    result = get_trend("Atlantis", "composite_score", 7, con=db_with_trend_data)
    assert result["trend"] == []


def test_get_trend_invalid_metric(db_with_trend_data):
    result = get_trend("Camden", "fake_metric", 7, con=db_with_trend_data)
    assert result["found"] is False


def test_get_trend_days_clamped_to_30(db_with_trend_data):
    result = get_trend("Camden", "composite_score", 999, con=db_with_trend_data)
    assert result["days"] == 30


def test_get_trend_days_clamped_to_1(db_with_trend_data):
    result = get_trend("Camden", "composite_score", -5, con=db_with_trend_data)
    assert result["days"] == 1


# ===========================================================================
# run_sql (synthetic)
# ===========================================================================

def test_run_sql_success(db_with_sql_data):
    result = run_sql(
        "SELECT borough_name, air_score FROM gold_scores ORDER BY air_score ASC",
        con=db_with_sql_data,
    )
    assert result["success"] is True


def test_run_sql_correct_columns(db_with_sql_data):
    result = run_sql(
        "SELECT borough_name, air_score FROM gold_scores ORDER BY air_score ASC",
        con=db_with_sql_data,
    )
    assert result["columns"] == ["borough_name", "air_score"]


def test_run_sql_correct_row_count(db_with_sql_data):
    result = run_sql(
        "SELECT borough_name, air_score FROM gold_scores ORDER BY air_score ASC",
        con=db_with_sql_data,
    )
    assert result["row_count"] == 2


def test_run_sql_rows_are_dicts(db_with_sql_data):
    result = run_sql(
        "SELECT borough_name, air_score FROM gold_scores ORDER BY air_score ASC",
        con=db_with_sql_data,
    )
    assert isinstance(result["rows"][0], dict)


def test_run_sql_correct_first_row(db_with_sql_data):
    result = run_sql(
        "SELECT borough_name, air_score FROM gold_scores ORDER BY air_score ASC",
        con=db_with_sql_data,
    )
    assert result["rows"][0]["borough_name"] == "Camden"


def test_run_sql_aggregation_success(db_with_sql_data):
    result = run_sql(
        "SELECT AVG(composite_score) AS avg_composite FROM gold_scores",
        con=db_with_sql_data,
    )
    assert result["success"] is True


def test_run_sql_aggregation_value(db_with_sql_data):
    result = run_sql(
        "SELECT AVG(composite_score) AS avg_composite FROM gold_scores",
        con=db_with_sql_data,
    )
    assert result["rows"][0]["avg_composite"] == pytest.approx(69.5)


def test_run_sql_multi_column_filter_success(db_with_sql_data):
    result = run_sql(
        "SELECT borough_name FROM gold_scores WHERE air_score > 50 AND transit_score > 80",
        con=db_with_sql_data,
    )
    assert result["success"] is True


def test_run_sql_multi_column_filter_result(db_with_sql_data):
    result = run_sql(
        "SELECT borough_name FROM gold_scores WHERE air_score > 50 AND transit_score > 80",
        con=db_with_sql_data,
    )
    assert len(result["rows"]) == 1
    assert result["rows"][0]["borough_name"] == "City of London"


def test_run_sql_agent_logs_blocked(db_with_sql_data):
    result = run_sql("SELECT * FROM agent_logs", con=db_with_sql_data)
    assert result["success"] is False


def test_run_sql_agent_logs_error_message(db_with_sql_data):
    result = run_sql("SELECT * FROM agent_logs", con=db_with_sql_data)
    assert "agent_logs" in result["error"]


def test_run_sql_bulletin_logs_blocked(db_with_sql_data):
    result = run_sql("SELECT * FROM bulletin_logs", con=db_with_sql_data)
    assert result["success"] is False


def test_run_sql_drop_blocked(db_with_sql_data):
    result = run_sql("DROP TABLE gold_scores", con=db_with_sql_data)
    assert result["success"] is False


def test_run_sql_drop_error_message(db_with_sql_data):
    result = run_sql("DROP TABLE gold_scores", con=db_with_sql_data)
    assert "SELECT" in result["error"] or "DROP" in result["error"]


def test_run_sql_insert_blocked(db_with_sql_data):
    result = run_sql(
        "INSERT INTO gold_scores VALUES ('x','x','x',0,0,0,0,0,'x','x')",
        con=db_with_sql_data,
    )
    assert result["success"] is False


def test_run_sql_delete_blocked(db_with_sql_data):
    result = run_sql("DELETE FROM gold_scores", con=db_with_sql_data)
    assert result["success"] is False


def test_run_sql_update_blocked(db_with_sql_data):
    result = run_sql("UPDATE gold_scores SET air_score = 100", con=db_with_sql_data)
    assert result["success"] is False


def test_run_sql_no_allowed_table_rejected(db_with_sql_data):
    result = run_sql("SELECT 1", con=db_with_sql_data)
    assert result["success"] is False


def test_run_sql_no_allowed_table_error_mentions_gold_scores(db_with_sql_data):
    result = run_sql("SELECT 1", con=db_with_sql_data)
    assert "gold_scores" in result["error"]


def test_run_sql_empty_query_rejected(db_with_sql_data):
    result = run_sql("", con=db_with_sql_data)
    assert result["success"] is False


def test_run_sql_auto_limit_applied(db_with_sql_data):
    """LIMIT 100 wrapper must cap results even when table has more rows."""
    # Insert 150 rows so the limit is exercised
    for i in range(150):
        db_with_sql_data.execute(
            """INSERT INTO gold_scores VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [f"E090000{i:02d}", f"Borough{i}", "2026-04-10T00:00:00+00",
             50.0, 50.0, 50.0, 50.0, 50.0,
             "2026-04-10T00:00:00+00", "gold"],
        )
    result = run_sql("SELECT * FROM gold_scores", con=db_with_sql_data)
    assert result["success"] is True
    assert result["row_count"] == 100, f"expected 100 rows, got {result['row_count']}"


def test_run_sql_explicit_limit_respected(db_with_sql_data):
    result = run_sql("SELECT * FROM gold_scores LIMIT 1", con=db_with_sql_data)
    assert result["row_count"] == 1


def test_run_sql_silver_metrics_queryable(db_with_sql_data):
    db_with_sql_data.execute(
        """
        INSERT INTO silver_metrics
        (borough_code, borough_name, timestamp, metric_name, raw_value,
         normalised_score, source, ingested_at, pipeline_stage)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            "E09000007", "Camden", "2026-04-09T12:00:00+00:00",
            "air_quality", 25.0, 34.0, "openaq",
            "2026-04-09T12:00:00+00:00", "silver",
        ],
    )
    result = run_sql("SELECT COUNT(*) AS cnt FROM silver_metrics", con=db_with_sql_data)
    assert result["success"] is True


def test_run_sql_silver_metrics_returns_data(db_with_sql_data):
    db_with_sql_data.execute(
        """
        INSERT INTO silver_metrics
        (borough_code, borough_name, timestamp, metric_name, raw_value,
         normalised_score, source, ingested_at, pipeline_stage)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            "E09000007", "Camden", "2026-04-09T12:00:00+00:00",
            "air_quality", 25.0, 34.0, "openaq",
            "2026-04-09T12:00:00+00:00", "silver",
        ],
    )
    result = run_sql("SELECT COUNT(*) AS cnt FROM silver_metrics", con=db_with_sql_data)
    assert result["rows"][0]["cnt"] == 1


def test_run_sql_syntax_error(db_with_sql_data):
    result = run_sql("SLECT * FORM gold_scores", con=db_with_sql_data)
    assert result["success"] is False


def test_run_sql_mixed_case_drop_blocked(db_with_sql_data):
    result = run_sql("dRoP TABLE gold_scores", con=db_with_sql_data)
    assert result["success"] is False


def test_run_sql_comment_stripping_concealed_keyword(db_with_sql_data):
    result = run_sql("SELECT 1 FROM gold_scores -- DROP TABLE", con=db_with_sql_data)
    assert result["success"] is True


def test_run_sql_join_with_agent_logs_blocked(db_with_sql_data):
    result = run_sql("SELECT * FROM gold_scores JOIN agent_logs ON 1=1", con=db_with_sql_data)
    assert result["success"] is False


# ---------------------------------------------------------------------------
# run_sql: comprehensive keyword blocklist tests (#1, #2)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("keyword", [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE",
    "REPLACE", "MERGE", "COPY", "EXPORT", "IMPORT", "LOAD", "INSTALL",
    "CALL", "PRAGMA", "SET", "ATTACH", "DETACH",
    "SUMMARIZE", "DESCRIBE", "EXPLAIN", "SHOW", "PREPARE", "EXECUTE",
    "CHECKPOINT", "VACUUM",
])
def test_run_sql_blocked_keyword(keyword, db_with_sql_data):
    """Every keyword in _BLOCKED_KEYWORDS must be rejected."""
    result = run_sql(f"{keyword} gold_scores", con=db_with_sql_data)
    assert result["success"] is False, f"{keyword} was not blocked"


@pytest.mark.parametrize("table", [
    "agent_logs", "bulletin_logs", "information_schema", "pg_catalog",
    "duckdb_tables", "duckdb_columns", "duckdb_schemas", "duckdb_views",
    "duckdb_constraints", "duckdb_indexes", "duckdb_functions",
    "duckdb_settings", "duckdb_extensions", "duckdb_types",
    "duckdb_dependencies", "sqlite_master", "sqlite_schema",
])
def test_run_sql_blocked_table(table, db_with_sql_data):
    """Every table in _BLOCKED_TABLES must be rejected."""
    result = run_sql(f"SELECT * FROM {table}", con=db_with_sql_data)
    assert result["success"] is False, f"table {table} was not blocked"


@pytest.mark.parametrize("sql", [
    "SELECT duckdb_tables() FROM gold_scores",
    "SELECT current_setting('home_directory') FROM gold_scores",
    "SELECT table_info('gold_scores') FROM gold_scores",
    "SELECT pragma_table_info('gold_scores') FROM gold_scores",
])
def test_run_sql_blocked_metadata_function(sql, db_with_sql_data):
    """Metadata introspection functions must be rejected."""
    result = run_sql(sql, con=db_with_sql_data)
    assert result["success"] is False, f"metadata function was not blocked: {sql}"


@pytest.mark.parametrize("sql", [
    "SELECT * FROM read_csv_auto('/etc/passwd'), gold_scores",
    "SELECT * FROM read_parquet('/tmp/x.parquet'), gold_scores",
    "SELECT * FROM read_json('/tmp/x.json'), gold_scores",
    "SELECT * FROM read_text('/etc/passwd'), gold_scores",
    "SELECT * FROM read_ndjson('/tmp/x.ndjson'), gold_scores",
    "SELECT http_get('https://evil.com') FROM gold_scores",
    "SELECT https_get('https://evil.com') FROM gold_scores",
    "SELECT httpfs('https://evil.com') FROM gold_scores",
])
def test_run_sql_blocked_file_function(sql, db_with_sql_data):
    """File-read and HTTP functions must be rejected."""
    result = run_sql(sql, con=db_with_sql_data)
    assert result["success"] is False, f"file function was not blocked: {sql}"


def test_run_sql_file_path_table_blocked(db_with_sql_data):
    result = run_sql("SELECT * FROM '/tmp/file.csv', gold_scores", con=db_with_sql_data)
    assert result["success"] is False

def test_run_sql_file_path_table_double_quotes_blocked(db_with_sql_data):
    result = run_sql('SELECT * FROM "/tmp/file.csv", gold_scores', con=db_with_sql_data)
    assert result["success"] is False


def test_run_sql_query_length_limit(db_with_sql_data):
    long_query = "SELECT * FROM gold_scores WHERE borough_name = '" + "x" * 10_001 + "'"
    result = run_sql(long_query, con=db_with_sql_data)
    assert result["success"] is False
    assert "too long" in result["error"].lower()


def test_run_sql_block_comment_hides_keyword(db_with_sql_data):
    """Block comments around a blocked keyword should be stripped, leaving the keyword exposed."""
    result = run_sql("/* DROP TABLE gold_scores */ SELECT * FROM gold_scores", con=db_with_sql_data)
    assert result["success"] is True  # comment stripped, only SELECT remains

def test_run_sql_nested_block_comment(db_with_sql_data):
    """Nested block comments: inner comment stripped but residual '*/' causes syntax error.

    The stripping loop uses non-greedy regex so '/* /* INSERT */' is removed
    first, leaving '*/ SELECT ...'.  The stray '*/' is harmless — DuckDB rejects
    the malformed SQL with an error, so the query never executes.
    """
    result = run_sql("/* /* INSERT */ */ SELECT * FROM gold_scores", con=db_with_sql_data)
    assert result["success"] is False  # residual '*/' makes query invalid

def test_run_sql_keyword_inside_block_comment_not_hidden(db_with_sql_data):
    """A keyword hidden inside only the comment text should not block the query."""
    result = run_sql("SELECT /* just a comment mentioning DROP */ * FROM gold_scores", con=db_with_sql_data)
    assert result["success"] is True


def test_run_sql_cte_with_blocked_table(db_with_sql_data):
    result = run_sql(
        "WITH x AS (SELECT * FROM agent_logs) SELECT * FROM gold_scores",
        con=db_with_sql_data,
    )
    assert result["success"] is False, "CTE referencing blocked table should be rejected"


def test_run_sql_semicolon_rejected(db_with_sql_data):
    result = run_sql("SELECT * FROM gold_scores; SELECT 1", con=db_with_sql_data)
    assert result["success"] is False
    assert "Multiple statements" in result["error"]


def test_run_sql_non_select_rejected(db_with_sql_data):
    """Non-SELECT statements should be rejected even if they reference allowed tables."""
    result = run_sql("SUMMARIZE gold_scores", con=db_with_sql_data)
    assert result["success"] is False


def test_resolve_borough_sql_injection_safe():
    """_resolve_borough uses parameterized queries — injection input returns None safely."""
    from agents.tools.borough_query import _resolve_borough
    import duckdb
    from pipeline.schemas import init_db
    con = duckdb.connect(":memory:")
    init_db(con)
    result = _resolve_borough("Camden'; DROP TABLE gold_scores --", con)
    assert result is None
    # Verify gold_scores still exists
    tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
    assert "gold_scores" in tables
    con.close()


# ---------------------------------------------------------------------------
# run_sql: UNION bypass with blocked tables
# ---------------------------------------------------------------------------

def test_run_sql_union_with_blocked_table(db_with_sql_data):
    """UNION SELECT from a blocked table must be rejected."""
    result = run_sql(
        "SELECT borough_code FROM gold_scores UNION SELECT id FROM agent_logs",
        con=db_with_sql_data,
    )
    assert result["success"] is False, "UNION with blocked table should be rejected"


def test_run_sql_subquery_with_blocked_table(db_with_sql_data):
    """Subquery referencing a blocked table must be rejected."""
    result = run_sql(
        "SELECT * FROM gold_scores WHERE borough_code IN (SELECT id FROM agent_logs)",
        con=db_with_sql_data,
    )
    assert result["success"] is False, "subquery with blocked table should be rejected"


# ---------------------------------------------------------------------------
# run_sql: detail table WHERE clause enforcement (guardrail #11)
# ---------------------------------------------------------------------------

def test_run_sql_detail_table_requires_where(db_with_sql_data):
    """silver_detail queries without WHERE must be rejected."""
    result = run_sql("SELECT * FROM silver_detail", con=db_with_sql_data)
    assert result["success"] is False
    assert "WHERE" in result["error"]


def test_run_sql_headlines_requires_where(db_with_sql_data):
    """silver_headlines queries without WHERE must be rejected."""
    result = run_sql("SELECT * FROM silver_headlines", con=db_with_sql_data)
    assert result["success"] is False
    assert "WHERE" in result["error"]


def test_run_sql_detail_table_with_where_allowed(db_with_sql_data):
    """silver_detail queries WITH a WHERE clause should succeed."""
    result = run_sql(
        "SELECT * FROM silver_detail WHERE borough_code = 'E09000007'",
        con=db_with_sql_data,
    )
    assert result["success"] is True


def test_run_sql_headlines_with_where_allowed(db_with_sql_data):
    """silver_headlines queries WITH a WHERE clause should succeed."""
    result = run_sql(
        "SELECT * FROM silver_headlines WHERE source = 'bbc'",
        con=db_with_sql_data,
    )
    assert result["success"] is True


# ---------------------------------------------------------------------------
# run_sql: detail table row limit (50 vs 100, guardrail #12)
# ---------------------------------------------------------------------------

def test_run_sql_detail_table_limit_50(db_with_sql_data):
    """Detail tables should be capped at 50 rows, not the default 100."""
    for i in range(70):
        db_with_sql_data.execute(
            """INSERT INTO silver_detail
            (borough_code, borough_name, timestamp, source, category, label,
             value, detail_text, ingested_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                "E09000007", "Camden", "2026-04-10T00:00:00+00",
                "met_police", "burglary", f"Street {i}",
                1.0, f"Detail row {i}",
                "2026-04-10T00:00:00+00",
            ],
        )
    result = run_sql(
        "SELECT * FROM silver_detail WHERE borough_code = 'E09000007'",
        con=db_with_sql_data,
    )
    assert result["success"] is True
    assert result["row_count"] == 50, f"expected 50-row limit for detail table, got {result['row_count']}"


# ---------------------------------------------------------------------------
# run_sql: text field truncation (guardrail #13)
# ---------------------------------------------------------------------------

def test_run_sql_text_truncation(db_with_sql_data):
    """detail_text, label, and title fields should be truncated at 200 chars."""
    long_text = "x" * 300
    db_with_sql_data.execute(
        """INSERT INTO silver_detail
        (borough_code, borough_name, timestamp, source, category, label,
         value, detail_text, ingested_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            "E09000007", "Camden", "2026-04-10T00:00:00+00",
            "met_police", "burglary", long_text,
            1.0, long_text,
            "2026-04-10T00:00:00+00",
        ],
    )
    result = run_sql(
        "SELECT label, detail_text FROM silver_detail WHERE borough_code = 'E09000007'",
        con=db_with_sql_data,
    )
    assert result["success"] is True
    row = result["rows"][0]
    # Truncation cuts at 200 chars + appends "..." = 203 total
    assert len(row["label"]) <= 203, f"label not truncated: {len(row['label'])} chars"
    assert row["label"].endswith("..."), "truncated label should end with '...'"
    assert len(row["detail_text"]) <= 203, f"detail_text not truncated: {len(row['detail_text'])} chars"
    assert row["detail_text"].endswith("..."), "truncated detail_text should end with '...'"


# ---------------------------------------------------------------------------
# run_sql: glob function blocked
# ---------------------------------------------------------------------------

def test_run_sql_glob_function_blocked():
    """glob() function must be rejected by the file-read blocklist regex.

    NOTE: We test the regex directly rather than calling run_sql because DuckDB
    may attempt to auto-load a filesystem extension when it encounters 'glob',
    which can hang in test environments.
    """
    import re
    from agents.tools.sql_query import _BLOCKED_FILE_FUNCTIONS
    assert _BLOCKED_FILE_FUNCTIONS.search("SELECT glob('/tmp/*') FROM gold_scores"), \
        "glob() should be matched by _BLOCKED_FILE_FUNCTIONS regex"


# ===========================================================================
# Metric allowlist
# ===========================================================================

def test_valid_metrics_set():
    expected = {
        "air_score", "transit_score", "sentiment_score",
        "immune_score", "composite_score",
    }
    assert _VALID_METRICS == expected


# ===========================================================================
# Real data integration (requires prior pipeline run)
# ===========================================================================

@pytest.mark.skipif(
    not __import__("pathlib").Path(__file__).resolve().parent.parent.joinpath(
        "data", "cityscan.duckdb"
    ).exists(),
    reason="cityscan.duckdb not found — run `python ingestion/run_pipeline.py` first",
)
class TestRealData:
    """Integration tests against live cityscan.duckdb."""

    @pytest.fixture(autouse=True)
    def real_con(self, gold_db_path):
        import duckdb
        con = duckdb.connect(gold_db_path, read_only=True)
        self.con = con
        yield
        con.close()

    def test_real_london_score_borough_count(self):
        result = get_london_score(con=self.con)
        assert result["borough_count"] == 33

    def test_real_london_composite_in_range(self):
        result = get_london_score(con=self.con)
        assert result["composite_score"] is not None
        assert 0 <= result["composite_score"] <= 100

    def test_real_camden_found(self):
        result = get_borough_health("Camden", con=self.con)
        assert result["found"] is True

    def test_real_camden_composite_in_range(self):
        result = get_borough_health("Camden", con=self.con)
        assert 0 <= result["composite_score"] <= 100

    def test_real_compare_returns_five_boroughs(self):
        result = compare_boroughs("composite_score", top_n=5, con=self.con)
        assert len(result["boroughs"]) == 5

    def test_real_compare_ranks_are_one_to_five(self):
        result = compare_boroughs("composite_score", top_n=5, con=self.con)
        assert [b["rank"] for b in result["boroughs"]] == [1, 2, 3, 4, 5]

    def test_real_trend_found(self):
        result = get_trend("Camden", "composite_score", 7, con=self.con)
        assert result["found"] is True

    def test_real_trend_has_data_points(self):
        result = get_trend("Camden", "composite_score", 7, con=self.con)
        assert result["data_points"] > 0

    def test_real_analytical_sql_success(self):
        result = run_sql(
            "SELECT borough_name, air_score, transit_score FROM gold_scores "
            "WHERE air_score IS NOT NULL AND transit_score IS NOT NULL "
            "ORDER BY air_score LIMIT 3",
            con=self.con,
        )
        assert result["success"] is True

    def test_real_analytical_sql_returns_rows(self):
        result = run_sql(
            "SELECT borough_name, air_score, transit_score FROM gold_scores "
            "WHERE air_score IS NOT NULL AND transit_score IS NOT NULL "
            "ORDER BY air_score LIMIT 3",
            con=self.con,
        )
        assert result["row_count"] > 0
