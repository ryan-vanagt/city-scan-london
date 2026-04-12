"""
Tool: get_london_score

Returns the current overall London composite health score, aggregated
across all 33 boroughs. Queries the Gold layer in DuckDB.
"""

import logging

import duckdb

from agents.tools.db import get_connection

logger = logging.getLogger(__name__)


def _avg(values: list[float | None]) -> float | None:
    """Average of non-None values, rounded to 2 decimal places."""
    present = [v for v in values if v is not None]
    return round(sum(present) / len(present), 2) if present else None


def get_london_score(
    *,
    con: duckdb.DuckDBPyConnection | None = None,
) -> dict:
    """Return the current overall London health score averaged across all boroughs.

    Queries the latest gold_scores row per borough and averages each sub-score
    and the composite score across all boroughs.

    Args:
        con: Optional DuckDB connection. Uses the shared lazy connection if None.

    Returns:
        Dict with composite_score, air_score, transit_score, sentiment_score,
        immune_score, borough_count, and timestamp.
    """
    if con is None:
        con = get_connection()

    _null_result = {
        "composite_score": None,
        "air_score": None,
        "transit_score": None,
        "sentiment_score": None,
        "immune_score": None,
        "borough_count": 0,
        "timestamp": None,
    }

    try:
        rows = con.execute("""
            SELECT borough_code, air_score, transit_score, sentiment_score,
                   immune_score, composite_score, timestamp
            FROM (
                SELECT *,
                       ROW_NUMBER() OVER (PARTITION BY borough_code ORDER BY ingested_at DESC) AS rn
                FROM gold_scores
            )
            WHERE rn = 1
        """).fetchall()
    except duckdb.Error as exc:
        logger.error("get_london_score: query failed: %s", exc)
        return _null_result

    if not rows:
        return _null_result

    # Use MAX(timestamp) for a deterministic timestamp across all boroughs
    max_ts = max(r[6] for r in rows if r[6] is not None)

    return {
        "composite_score": _avg([r[5] for r in rows]),
        "air_score": _avg([r[1] for r in rows]),
        "transit_score": _avg([r[2] for r in rows]),
        "sentiment_score": _avg([r[3] for r in rows]),
        "immune_score": _avg([r[4] for r in rows]),
        "borough_count": len(rows),
        "timestamp": str(max_ts) if max_ts is not None else None,
    }
