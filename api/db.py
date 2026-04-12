"""
Shared DuckDB connection for the API layer.

Provides a read-only connection to cityscan.duckdb. Tables are initialised
on import (idempotent). Use get_connection() as a FastAPI dependency.
"""

import logging
import time
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = str(PROJECT_ROOT / "data" / "cityscan.duckdb")

_con: duckdb.DuckDBPyConnection | None = None

# Max time to wait for the ingestion service to create the database
_DB_WAIT_TIMEOUT = 600  # 10 minutes
_DB_POLL_INTERVAL = 5   # check every 5 seconds


def open_connection() -> None:
    """Open a read-only DuckDB connection. Called at app startup.

    Waits up to 5 minutes for the database file to be created by the
    ingestion service (which runs the pipeline on startup).
    """
    global _con
    db_path = Path(DB_PATH)

    if not db_path.exists():
        logger.info("Database not found at %s — waiting for ingestion service to create it...", DB_PATH)
        waited = 0
        while not db_path.exists() and waited < _DB_WAIT_TIMEOUT:
            time.sleep(_DB_POLL_INTERVAL)
            waited += _DB_POLL_INTERVAL
            if waited % 30 == 0:
                logger.info("Still waiting for database... (%ds elapsed)", waited)

        if not db_path.exists():
            raise RuntimeError(
                f"Database not created after {_DB_WAIT_TIMEOUT}s — "
                f"check ingestion service logs"
            )

    _con = duckdb.connect(DB_PATH, read_only=True)
    logger.info("DuckDB connection opened (read-only): %s", DB_PATH)


def close_connection() -> None:
    """Close the DuckDB connection. Called at app shutdown."""
    global _con
    if _con is not None:
        _con.close()
        _con = None
        logger.info("DuckDB connection closed")


def get_connection() -> duckdb.DuckDBPyConnection:
    """Return the shared DuckDB connection. Use as a FastAPI Depends()."""
    if _con is None:
        raise RuntimeError("DuckDB connection not initialised — call open_connection() first")
    return _con.cursor()
