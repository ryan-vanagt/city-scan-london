"""
Health check and London-level score endpoints.

GET /health          — service liveness check
GET /london/score    — current overall London composite health score
"""

import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

import duckdb

from agents.tools.db import close_connection as close_tools_connection
from api.db import get_connection, reset_connection

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
def health_check() -> dict:
    """Service liveness check — never touches DuckDB.

    This endpoint is hit every 30s by the Docker health check. It must NOT
    open a DuckDB connection, because a read-only connection would block the
    ingestion service from writing. DuckDB connectivity is verified implicitly
    by the data endpoints instead.
    """
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


_INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "")


@router.post("/internal/reset-db")
def reset_db(request: Request) -> dict:
    """Release the read-only DuckDB connection so ingestion can write.

    Called by the ingestion scheduler before each pipeline write cycle.
    Protected by INTERNAL_TOKEN env var — if set, requests must include
    a matching X-Internal-Token header.
    """
    if _INTERNAL_TOKEN and request.headers.get("X-Internal-Token") != _INTERNAL_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")
    reset_connection()
    close_tools_connection()
    logger.info("DuckDB connections reset")
    return {"status": "reset"}


@router.get("/london/score")
def london_score(con: duckdb.DuckDBPyConnection = Depends(get_connection)) -> dict:
    """Overall London health score averaged across all boroughs.

    Returns the mean of each sub-score and composite across the latest
    gold_scores row per borough.
    """
    try:
        rows = con.execute("""
            SELECT borough_code, air_score, transit_score, sentiment_score,
                   immune_score, green_space_score, green_space_access_score,
                   composite_score, timestamp
            FROM (
                SELECT *,
                       ROW_NUMBER() OVER (PARTITION BY borough_code ORDER BY ingested_at DESC) AS rn
                FROM gold_scores
            )
            WHERE rn = 1
        """).fetchall()
    except duckdb.Error as exc:
        logger.error("london_score: query failed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Gold scores not yet available",
        ) from exc

    if not rows:
        return {
            "composite_score": None,
            "air_score": None,
            "transit_score": None,
            "sentiment_score": None,
            "immune_score": None,
            "green_space_score": None,
            "green_space_access_score": None,
            "borough_count": 0,
            "timestamp": None,
        }

    def _avg(values: list[float | None]) -> float | None:
        present = [v for v in values if v is not None]
        return round(sum(present) / len(present), 2) if present else None

    return {
        "composite_score": _avg([r[7] for r in rows]),
        "air_score": _avg([r[1] for r in rows]),
        "transit_score": _avg([r[2] for r in rows]),
        "sentiment_score": _avg([r[3] for r in rows]),
        "immune_score": _avg([r[4] for r in rows]),
        "green_space_score": _avg([r[5] for r in rows]),
        "green_space_access_score": _avg([r[6] for r in rows]),
        "borough_count": len(rows),
        "timestamp": str(rows[0][8]),
    }
