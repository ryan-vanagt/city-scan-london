"""Shared pytest fixtures for CityScan tests."""

import sys
from pathlib import Path

import duckdb
import pytest

# Ensure project root is on sys.path for all tests
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.schemas import BOROUGHS, init_db


@pytest.fixture
def fresh_db():
    """Create an in-memory DuckDB with schema initialised."""
    con = duckdb.connect(":memory:")
    init_db(con)
    yield con
    con.close()


@pytest.fixture
def gold_db_path():
    """Return path to cityscan.duckdb, skip if missing."""
    path = PROJECT_ROOT / "data" / "cityscan.duckdb"
    if not path.exists():
        pytest.skip("cityscan.duckdb not found — run pipeline first")
    return str(path)


def insert_silver(
    con: duckdb.DuckDBPyConnection,
    borough_code: str,
    metric_name: str,
    score: float,
    source: str = "",
    ingested_at: str | None = None,
) -> None:
    """Insert a single silver_metrics row (for deterministic edge-case tests only)."""
    from datetime import datetime, timezone

    borough_name = BOROUGHS[borough_code]["name"]
    if not source:
        source = metric_name
    if ingested_at is None:
        ingested_at = datetime.now(timezone.utc).isoformat()
    timestamp = ingested_at
    con.execute(
        """
        INSERT INTO silver_metrics
        (borough_code, borough_name, timestamp, metric_name, raw_value,
         normalised_score, source, ingested_at, pipeline_stage)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [borough_code, borough_name, timestamp,
         metric_name, score, score, source, ingested_at, "silver"],
    )
