"""
Tool: get_trend

Returns the trend direction and delta for a given borough and metric
over the last N days. Queries the Gold layer in DuckDB.
"""

import logging

import duckdb

from agents.tools.borough_query import _resolve_borough, _VALID_METRICS
from agents.tools.db import get_connection

logger = logging.getLogger(__name__)

# Score change must exceed this threshold to be classified as improving/declining
_DIRECTION_THRESHOLD = 2.0


def get_trend(
    borough: str,
    metric: str = "composite_score",
    days: int = 7,
    *,
    con: duckdb.DuckDBPyConnection | None = None,
) -> dict:
    """Return the score trend for a borough over the last N days.

    Computes direction (improving/declining/stable) and delta from the
    first to last data point in the window. A change of more than 2.0
    points is required to register as improving or declining.

    Args:
        borough: Borough name (case-insensitive) or ONS 9-char code.
        metric: Score column to track. Must be one of air_score,
            transit_score, sentiment_score, immune_score, composite_score.
        days: Lookback window in days (clamped to 1–30).
        con: Optional DuckDB connection. Uses the shared lazy connection if None.

    Returns:
        Dict with found, borough_code, borough_name, metric, days,
        data_points, direction, delta, and a list of trend data points.
    """
    if con is None:
        con = get_connection()

    _not_found = {
        "found": False,
        "borough_code": None,
        "borough_name": None,
        "metric": metric,
        "days": days,
        "data_points": 0,
        "direction": None,
        "delta": None,
        "trend": [],
    }

    if metric not in _VALID_METRICS:
        logger.warning("get_trend: invalid metric '%s'", metric)
        return _not_found

    days = max(1, min(days, 30))

    try:
        resolved = _resolve_borough(borough, con)
        if resolved is None:
            return _not_found

        borough_code, borough_name = resolved

        rows = con.execute(f"""
            SELECT timestamp, {metric}
            FROM gold_scores
            WHERE borough_code = ?
              AND timestamp >= NOW() - INTERVAL {int(days)} DAY
            ORDER BY timestamp ASC
        """, [borough_code]).fetchall()
    except duckdb.Error as exc:
        logger.error("get_trend: query failed: %s", exc)
        return _not_found

    trend = [
        {"timestamp": str(r[0]), "score": r[1]}
        for r in rows
    ]

    # Compute direction from first to last non-None score
    scores = [p["score"] for p in trend if p["score"] is not None]
    direction: str | None = None
    delta: float | None = None

    if len(scores) >= 2:
        delta = round(scores[-1] - scores[0], 2)
        if delta > _DIRECTION_THRESHOLD:
            direction = "improving"
        elif delta < -_DIRECTION_THRESHOLD:
            direction = "declining"
        else:
            direction = "stable"

    return {
        "found": True,
        "borough_code": borough_code,
        "borough_name": borough_name,
        "metric": metric,
        "days": days,
        "data_points": len(trend),
        "direction": direction,
        "delta": delta,
        "trend": trend,
    }
