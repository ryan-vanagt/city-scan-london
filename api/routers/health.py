"""
Health check and London-level score endpoints.

GET /health          — service liveness check
GET /london/score    — current overall London composite health score
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

import duckdb

from api.db import get_connection

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
def health_check(con: duckdb.DuckDBPyConnection = Depends(get_connection)) -> dict:
    """Service liveness check. Pings DuckDB to verify the database is reachable."""
    try:
        con.execute("SELECT 1").fetchone()
        db_status = "connected"
    except Exception as exc:
        logger.error("Health check: database ping failed: %s", exc)
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "database": "error",
            },
        )

    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": db_status,
    }


@router.get("/london/score")
def london_score(con: duckdb.DuckDBPyConnection = Depends(get_connection)) -> dict:
    """Overall London health score averaged across all boroughs.

    Returns the mean of each sub-score and composite across the latest
    gold_scores row per borough.
    """
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
        logger.error("london_score: query failed: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"detail": "Gold scores not yet available"},
        )

    if not rows:
        return {
            "composite_score": None,
            "air_score": None,
            "transit_score": None,
            "sentiment_score": None,
            "immune_score": None,
            "borough_count": 0,
            "timestamp": None,
        }

    def _avg(values: list[float | None]) -> float | None:
        present = [v for v in values if v is not None]
        return round(sum(present) / len(present), 2) if present else None

    return {
        "composite_score": _avg([r[5] for r in rows]),
        "air_score": _avg([r[1] for r in rows]),
        "transit_score": _avg([r[2] for r in rows]),
        "sentiment_score": _avg([r[3] for r in rows]),
        "immune_score": _avg([r[4] for r in rows]),
        "borough_count": len(rows),
        "timestamp": str(rows[0][6]),
    }
