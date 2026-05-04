"""
Borough data endpoints.

GET /boroughs                          — all 33 boroughs with current composite scores
GET /boroughs/deprivation              — all 33 boroughs with static IMD deprivation data
GET /boroughs/housing-affordability    — all 33 boroughs with ONS housing affordability ratios
GET /boroughs/trends                   — 7-day composite trend direction for all boroughs
GET /borough/{name}                    — full organ breakdown for a single borough
GET /borough/{name}/trend              — 7-day trend for a single borough
"""

import json
import logging
from enum import Enum
from functools import lru_cache
from pathlib import Path as FilePath

from fastapi import APIRouter, Depends, HTTPException, Path, Query

import duckdb

from api.db import get_connection

logger = logging.getLogger(__name__)

router = APIRouter()


class SortField(str, Enum):
    """Allowed sort fields for the boroughs list endpoint."""
    composite_score = "composite_score"
    air_score = "air_score"
    air_quality_modelled_score = "air_quality_modelled_score"
    transit_score = "transit_score"
    sentiment_score = "sentiment_score"
    immune_score = "immune_score"
    green_space_score = "green_space_score"
    green_space_access_score = "green_space_access_score"


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
        "air_quality_modelled_score": row[4],
        "transit_score": row[5],
        "sentiment_score": row[6],
        "immune_score": row[7],
        "green_space_score": row[8],
        "green_space_access_score": row[9],
        "composite_score": row[10],
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
               air_score, air_quality_modelled_score,
               transit_score, sentiment_score,
               immune_score, green_space_score, green_space_access_score,
               composite_score
        FROM (
            SELECT *,
                   ROW_NUMBER() OVER (PARTITION BY borough_code ORDER BY ingested_at DESC) AS rn
            FROM gold_scores
        )
        WHERE rn = 1
        ORDER BY {sort_by.value} DESC NULLS LAST
    """).fetchall()

    return [_borough_row_to_dict(r) for r in rows]


IMD_FILE = FilePath(__file__).resolve().parents[2] / "data" / "static" / "imd_borough.json"


@lru_cache(maxsize=1)
def _load_imd_data() -> list[dict]:
    """Load and cache IMD borough data from the static JSON file.

    Returns a list of borough dicts ready for the API response.
    Raises FileNotFoundError if the file does not exist.
    """
    raw = json.loads(IMD_FILE.read_text(encoding="utf-8"))
    boroughs = raw.get("boroughs", {})
    result = []
    for code, data in boroughs.items():
        result.append({
            "borough_code": code,
            "borough_name": data["name"],
            "imd_rank": data["imd_rank"],
            "imd_score": data["imd_score"],
            "pct_most_deprived_10": data["pct_most_deprived_10"],
            "domains": data.get("domains", {}),
        })
    return result


@router.get("/boroughs/deprivation")
def list_boroughs_deprivation() -> list[dict]:
    """All 33 boroughs with their IMD deprivation data (static dataset)."""
    try:
        return _load_imd_data()
    except FileNotFoundError:
        logger.error("IMD data file not found: %s", IMD_FILE)
        raise HTTPException(status_code=404, detail="IMD deprivation data not available")
    except (json.JSONDecodeError, KeyError) as exc:
        logger.error("Failed to parse IMD data file: %s", exc)
        raise HTTPException(status_code=500, detail="IMD deprivation data is malformed")


HOUSING_FILE = FilePath(__file__).resolve().parents[2] / "data" / "static" / "housing_affordability.json"


@lru_cache(maxsize=1)
def _load_housing_data() -> list[dict]:
    """Load and cache ONS housing affordability ratios from the static JSON file.

    Source: ONS Table 5c (median house price ÷ median workplace-based earnings)
    by local authority district. Annual cadence; static file refreshed via
    scripts/refresh_housing_affordability.py.
    """
    raw = json.loads(HOUSING_FILE.read_text(encoding="utf-8"))
    metadata = raw.get("_metadata", {})
    boroughs = raw.get("boroughs", {})
    result = []
    for code, data in boroughs.items():
        result.append({
            "borough_code": code,
            "borough_name": data["name"],
            "ratio": data.get("ratio_2025"),
            "ratio_5yr_avg": data.get("ratio_5yr_avg"),
            "year": metadata.get("year"),
        })
    return result


@router.get("/boroughs/housing-affordability")
def list_boroughs_housing_affordability() -> list[dict]:
    """All 33 boroughs with their ONS housing affordability ratios (static)."""
    try:
        return _load_housing_data()
    except FileNotFoundError:
        logger.error("Housing affordability file not found: %s", HOUSING_FILE)
        raise HTTPException(status_code=404, detail="Housing affordability data not available")
    except (json.JSONDecodeError, KeyError) as exc:
        logger.error("Failed to parse housing affordability file: %s", exc)
        raise HTTPException(status_code=500, detail="Housing affordability data is malformed")


@router.get("/boroughs/trends")
def borough_trends(
    days: int = Query(7, ge=1, le=30),
    con: duckdb.DuckDBPyConnection = Depends(get_connection),
) -> list[dict]:
    """7-day composite trend direction for all boroughs.

    Returns each borough with a direction (improving/declining/stable)
    and delta based on earliest vs latest composite_score in the window.
    Boroughs with fewer than 3 data points get direction=null, delta=null.
    Threshold of 2.0 matches agents/tools/trend_analysis._DIRECTION_THRESHOLD.
    """
    try:
        rows = con.execute(f"""
            WITH windowed AS (
                SELECT borough_code, borough_name,
                       FIRST_VALUE(composite_score) OVER (
                           PARTITION BY borough_code ORDER BY timestamp ASC
                       ) AS earliest,
                       LAST_VALUE(composite_score) OVER (
                           PARTITION BY borough_code ORDER BY timestamp ASC
                           ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                       ) AS latest,
                       COUNT(*) OVER (PARTITION BY borough_code) AS n
                FROM gold_scores
                WHERE timestamp >= NOW() - INTERVAL {int(days)} DAY
            )
            SELECT DISTINCT borough_code, borough_name, earliest, latest, n
            FROM windowed
            ORDER BY borough_name
        """).fetchall()
    except Exception:
        logger.exception("Failed to fetch borough trends")
        return []

    result = []
    for row in rows:
        code, name, earliest, latest, n = row
        if n < 3 or earliest is None or latest is None:
            result.append({
                "borough_code": code,
                "borough_name": name,
                "direction": None,
                "delta": None,
            })
        else:
            delta = round(latest - earliest, 1)
            if delta > 2.0:
                direction = "improving"
            elif delta < -2.0:
                direction = "declining"
            else:
                direction = "stable"
            result.append({
                "borough_code": code,
                "borough_name": name,
                "direction": direction,
                "delta": delta,
            })
    return result


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
               air_score, air_quality_modelled_score,
               transit_score, sentiment_score,
               immune_score, green_space_score, green_space_access_score,
               composite_score
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
        SELECT timestamp, air_score, air_quality_modelled_score,
               transit_score, sentiment_score,
               immune_score, green_space_score, green_space_access_score,
               composite_score
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
                "air_quality_modelled_score": r[2],
                "transit_score": r[3],
                "sentiment_score": r[4],
                "immune_score": r[5],
                "green_space_score": r[6],
                "green_space_access_score": r[7],
                "composite_score": r[8],
            }
            for r in rows
        ],
    }
