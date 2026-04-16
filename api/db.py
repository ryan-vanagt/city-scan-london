"""
Shared DuckDB connection for the API layer.

Provides a read-only connection to cityscan.duckdb. The connection opens
lazily on first real data request (not at startup and not from health checks)
so the ingestion service has time to write first.
"""

import logging
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = str(PROJECT_ROOT / "data" / "cityscan_read.duckdb")
DB_WRITE_PATH = str(PROJECT_ROOT / "data" / "cityscan.duckdb")  # Used only for existence check

_con: duckdb.DuckDBPyConnection | None = None


def open_connection() -> None:
    """No-op — connection is opened lazily on first request.

    Kept for backwards compatibility with the lifespan hook in main.py.
    """
    pass


def close_connection() -> None:
    """Close the DuckDB connection. Called at app shutdown."""
    global _con
    if _con is not None:
        _con.close()
        _con = None
        logger.info("DuckDB connection closed")


def reset_connection() -> None:
    """Close the read-only connection so the ingestion service can write.

    Called via POST /internal/reset-db before each pipeline write cycle.
    The next API request will lazily reopen the connection.
    """
    global _con
    if _con is not None:
        _con.close()
        _con = None
        logger.info("DuckDB connection reset (released for ingestion write)")


def get_connection() -> duckdb.DuckDBPyConnection:
    """Return a DuckDB cursor from the shared connection, opened lazily.

    Returns a cursor (not the raw connection) so FastAPI dependency injection
    gives each request its own cursor. Callers do not need to close cursors
    explicitly — DuckDB cursors are lightweight and garbage-collected. The
    underlying connection is closed via close_connection() at app shutdown.

    Raises RuntimeError if the database file doesn't exist yet or is locked
    by the ingestion writer. The caller should handle this gracefully.
    """
    global _con
    if _con is None:
        db_path = Path(DB_PATH)
        if not db_path.exists():
            # Check if write DB exists but read replica hasn't been created yet
            if Path(DB_WRITE_PATH).exists():
                raise RuntimeError("Pipeline ran but read replica not yet created — try again shortly")
            raise RuntimeError("Database not created yet — ingestion pipeline has not run")
        try:
            _con = duckdb.connect(DB_PATH, read_only=True)
            logger.info("DuckDB connection opened (read-only): %s", DB_PATH)
        except duckdb.IOException as exc:
            raise RuntimeError("Database locked by ingestion pipeline") from exc
    return _con.cursor()
