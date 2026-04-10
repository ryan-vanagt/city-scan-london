"""
Tools: get_borough_health, compare_boroughs

get_borough_health — returns the full score breakdown for a single borough
                     from the DuckDB Gold layer.

compare_boroughs   — ranks all boroughs by a given signal (air, transit,
                     sentiment, immune, or composite) and returns the top N.
"""

import logging

import duckdb

from agents.tools.db import get_connection

logger = logging.getLogger(__name__)

_VALID_METRICS = frozenset({
    "air_score",
    "transit_score",
    "sentiment_score",
    "immune_score",
    "composite_score",
})


def _resolve_borough(
    borough: str,
    con: duckdb.DuckDBPyConnection,
) -> tuple[str, str] | None:
    """Resolve a borough name or ONS code to (borough_code, borough_name).

    Accepts ONS 9-char codes (e.g. 'E09000007') or borough names
    (case-insensitive, e.g. 'camden', 'City of London').

    Returns None if not found in gold_scores.
    """
    if not borough or not borough.strip():
        return None

    borough = borough.strip()

    # Check if it looks like an ONS code
    if borough.startswith("E0") and len(borough) == 9:
        row = con.execute(
            "SELECT DISTINCT borough_code, borough_name FROM gold_scores WHERE borough_code = ?",
            [borough],
        ).fetchone()
        return (row[0], row[1]) if row else None

    # Otherwise search by name (case-insensitive)
    row = con.execute(
        "SELECT DISTINCT borough_code, borough_name FROM gold_scores WHERE LOWER(borough_name) = LOWER(?)",
        [borough],
    ).fetchone()
    return (row[0], row[1]) if row else None


def get_borough_health(
    borough: str,
    *,
    con: duckdb.DuckDBPyConnection | None = None,
) -> dict:
    """Return the full health score breakdown for a single borough.

    Accepts borough name (case-insensitive) or ONS code. Returns
    found=False with None scores if the borough is not in gold_scores.

    Args:
        borough: Borough name or ONS 9-char code.
        con: Optional DuckDB connection. Uses the shared lazy connection if None.

    Returns:
        Dict with found, borough_code, borough_name, timestamp, and all
        sub-scores plus composite_score.
    """
    if con is None:
        con = get_connection()

    _not_found = {
        "found": False,
        "borough_code": None,
        "borough_name": None,
        "timestamp": None,
        "air_score": None,
        "transit_score": None,
        "sentiment_score": None,
        "immune_score": None,
        "composite_score": None,
    }

    try:
        resolved = _resolve_borough(borough, con)
        if resolved is None:
            return _not_found

        borough_code, borough_name = resolved

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
    except duckdb.Error as exc:
        logger.error("get_borough_health: query failed: %s", exc)
        return _not_found

    if row is None:
        return _not_found

    return {
        "found": True,
        "borough_code": row[0],
        "borough_name": row[1],
        "timestamp": str(row[2]),
        "air_score": row[3],
        "transit_score": row[4],
        "sentiment_score": row[5],
        "immune_score": row[6],
        "composite_score": row[7],
    }


def compare_boroughs(
    metric: str = "composite_score",
    top_n: int = 5,
    ascending: bool = False,
    *,
    con: duckdb.DuckDBPyConnection | None = None,
) -> dict:
    """Rank all boroughs by a health metric and return the top N.

    Args:
        metric: Score column to rank by. Must be one of air_score,
            transit_score, sentiment_score, immune_score, composite_score.
        top_n: Number of boroughs to return (clamped to 1–33).
        ascending: If False (default), best boroughs first (highest score).
            If True, worst boroughs first (lowest score).
        con: Optional DuckDB connection. Uses the shared lazy connection if None.

    Returns:
        Dict with metric, order ('best_first' or 'worst_first'), and a
        list of ranked boroughs with rank, borough_code, borough_name, score.
    """
    if con is None:
        con = get_connection()

    if metric not in _VALID_METRICS:
        logger.warning("compare_boroughs: invalid metric '%s'", metric)
        return {
            "metric": metric,
            "order": "worst_first" if ascending else "best_first",
            "boroughs": [],
        }

    top_n = max(1, min(top_n, 33))
    direction = "ASC" if ascending else "DESC"

    try:
        rows = con.execute(f"""
            SELECT borough_code, borough_name, {metric}
            FROM (
                SELECT *,
                       ROW_NUMBER() OVER (PARTITION BY borough_code ORDER BY ingested_at DESC) AS rn
                FROM gold_scores
            )
            WHERE rn = 1
            ORDER BY {metric} {direction} NULLS LAST
            LIMIT ?
        """, [top_n]).fetchall()
    except duckdb.Error as exc:
        logger.error("compare_boroughs: query failed: %s", exc)
        return {
            "metric": metric,
            "order": "worst_first" if ascending else "best_first",
            "boroughs": [],
        }

    return {
        "metric": metric,
        "order": "worst_first" if ascending else "best_first",
        "boroughs": [
            {
                "rank": i + 1,
                "borough_code": r[0],
                "borough_name": r[1],
                "score": r[2],
            }
            for i, r in enumerate(rows)
        ],
    }
