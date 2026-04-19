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

    On cold start (replica missing but write DB present), bootstraps the
    replica with an atomic copy so the API doesn't 500 for up to an hour
    waiting for the scheduler's next cycle. Safe because the scheduler's
    own copy is tempfile+rename atomic — a concurrent scheduler copy will
    simply replace our bootstrap snapshot with a fresher one.

    Raises RuntimeError if neither DB file exists or if the connection is
    locked by the ingestion writer. The caller should handle this gracefully.
    """
    global _con
    if _con is None:
        db_path = Path(DB_PATH)
        write_path = Path(DB_WRITE_PATH)
        if not db_path.exists():
            if write_path.exists():
                # Cold-start bootstrap: copy the write DB to the replica so
                # the API has something to read until the scheduler's next
                # atomic copy replaces it.
                try:
                    import shutil
                    shutil.copy2(write_path, db_path)
                    logger.info(
                        "DuckDB cold-start: bootstrapped read replica from %s",
                        write_path,
                    )
                except OSError as exc:
                    raise RuntimeError(
                        f"Could not bootstrap read replica from write DB: {exc}"
                    ) from exc
            else:
                raise RuntimeError("Database not created yet — ingestion pipeline has not run")
        try:
            _con = duckdb.connect(DB_PATH, read_only=True)
            logger.info("DuckDB connection opened (read-only): %s", DB_PATH)
        except duckdb.IOException as exc:
            raise RuntimeError("Database locked by ingestion pipeline") from exc
    return _con.cursor()
