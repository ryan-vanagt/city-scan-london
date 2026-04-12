"""
Borough data endpoints.

GET /boroughs              — all 33 boroughs with current composite scores
GET /borough/{name}        — full organ breakdown for a single borough
GET /borough/{name}/trend  — 7-day trend for a single borough
"""

import logging
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Path, Query

import duckdb

from api.db import get_connection

logger = logging.getLogger(__name__)

router = APIRouter()


class SortField(str, Enum):
    """Allowed sort fields for the boroughs list endpoint."""
    composite_score = "composite_score"
    air_score = "air_score"
    transit_score = "transit_score"
    sentiment_score = "sentiment_score"
    immune_score = "immune_score"


def _resolve_borough_code(name_or_code: str, con: duckdb.DuckDBPyConnection) -> str | None:
    """Resolve a borough name or ONS code to a borough_code.

    Accepts:
        - ONS 9-char code directly (e.g. "E09000007")
        - Borough name, case-insensitive (e.g. "camden", "City of London")

    Returns:
        The ONS borough code, or None if not found.
    """
    # Check if it looks like an ONS code
    if name_or_code.startswith("E0") and len(name_or_code) == 9:
        row = con.execute(
            "SELECT DISTINCT borough_code FROM gold_scores WHERE borough_code = ?",
            [name_or_code],
        ).fetchone()
        return row[0] if row else None

    # Otherwise search by name (case-insensitive)
    row = con.execute(
        "SELECT DISTINCT borough_code FROM gold_scores WHERE LOWER(borough_name) = LOWER(?)",
        [name_or_code],
    ).fetchone()
    return row[0] if row else None


def _borough_row_to_dict(row: tuple) -> dict:
    """Convert a gold_scores row tuple to a response dict."""
    return {
        "borough_code": row[0],
        "borough_name": row[1],
        "timestamp": str(row[2]),
        "air_score": row[3],
        "transit_score": row[4],
        "sentiment_score": row[5],
        "immune_score": row[6],
        "composite_score": row[7],
    }


@router.get("/boroughs")
def list_boroughs(
    sort_by: SortField = SortField.composite_score,
    con: duckdb.DuckDBPyConnection = Depends(get_connection),
) -> list[dict]:
    """All boroughs with their latest health scores, sorted by a chosen field.

    Boroughs with a NULL value in the sort field are placed at the end.
    """
    rows = con.execute(f"""
        SELECT borough_code, borough_name, timestamp,
               air_score, transit_score, sentiment_score,
               immune_score, composite_score
        FROM (
            SELECT *,
                   ROW_NUMBER() OVER (PARTITION BY borough_code ORDER BY ingested_at DESC) AS rn
            FROM gold_scores
        )
        WHERE rn = 1
        ORDER BY {sort_by.value} DESC NULLS LAST
    """).fetchall()

    return [_borough_row_to_dict(r) for r in rows]


@router.get("/borough/{name}")
def get_borough(
    name: str = Path(max_length=50),
    con: duckdb.DuckDBPyConnection = Depends(get_connection),
) -> dict:
    """Full health score breakdown for a single borough.

    Accepts borough name (case-insensitive) or ONS code (e.g. E09000007).
    """
    borough_code = _resolve_borough_code(name, con)
    if borough_code is None:
        raise HTTPException(status_code=404, detail="Borough not found")

    row = con.execute("""
        SELECT borough_code, borough_name, timestamp,
               air_score, transit_score, sentiment_score,
               immune_score, composite_score
        FROM (
            SELECT *,
                   ROW_NUMBER() OVER (PARTITION BY borough_code ORDER BY ingested_at DESC) AS rn
            FROM gold_scores
        )
        WHERE rn = 1 AND borough_code = ?
    """, [borough_code]).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Borough not found")

    return _borough_row_to_dict(row)


@router.get("/borough/{name}/trend")
def get_borough_trend(
    name: str = Path(max_length=50),
    days: int = Query(default=7, ge=1, le=30),
    con: duckdb.DuckDBPyConnection = Depends(get_connection),
) -> dict:
    """Score trend for a single borough over the last N days.

    Returns timestamped composite scores for charting, plus sub-score
    breakdowns at each data point.
    """
    borough_code = _resolve_borough_code(name, con)
    if borough_code is None:
        raise HTTPException(status_code=404, detail="Borough not found")

    # int(days) ensures the value is a safe integer — prevents SQL injection
    # in the f-string interpolation. FastAPI's Query(ge=1, le=30) validates
    # the range, but int() is the injection guard.
    rows = con.execute(f"""
        SELECT timestamp, air_score, transit_score, sentiment_score,
               immune_score, composite_score
        FROM gold_scores
        WHERE borough_code = ?
          AND timestamp >= NOW() - INTERVAL {int(days)} DAY
        ORDER BY timestamp ASC
    """, [borough_code]).fetchall()

    return {
        "borough_code": borough_code,
        "days": days,
        "data_points": len(rows),
        "trend": [
            {
                "timestamp": str(r[0]),
                "air_score": r[1],
                "transit_score": r[2],
                "sentiment_score": r[3],
                "immune_score": r[4],
                "composite_score": r[5],
            }
            for r in rows
        ],
    }
