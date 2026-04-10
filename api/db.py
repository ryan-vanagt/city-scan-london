"""
Shared DuckDB connection for the API layer.

Provides a read-only connection to cityscan.duckdb. Tables are initialised
on import (idempotent). Use get_connection() as a FastAPI dependency.
"""

import logging
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = str(PROJECT_ROOT / "data" / "cityscan.duckdb")

_con: duckdb.DuckDBPyConnection | None = None


def open_connection() -> None:
    """Open a read-only DuckDB connection. Called at app startup."""
    global _con
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
