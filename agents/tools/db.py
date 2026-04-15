"""
Shared DuckDB connection for agent tools.

Provides a read-only DuckDB connection that can be:
  1. Auto-managed (opened lazily on first call, closed with close_connection())
  2. Externally injected (pass an existing connection to any tool function)

The API layer passes its own connection via FastAPI Depends().
The MCP server and standalone scripts use the auto-managed connection.
"""

import logging
import threading
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = str(PROJECT_ROOT / "data" / "cityscan.duckdb")

_con: duckdb.DuckDBPyConnection | None = None
_lock = threading.Lock()


def get_connection() -> duckdb.DuckDBPyConnection:
    """Return a cursor from the shared read-only DuckDB connection.

    DuckDB connections are NOT thread-safe, but cursors derived from them
    are independent. Each tool call gets its own cursor, preventing the
    'closed pending query result' segfault when LangGraph runs tools
    concurrently in different threads.
    """
    global _con
    if _con is None:
        with _lock:
            if _con is None:
                new_con = duckdb.connect(DB_PATH, read_only=True)
                try:
                    new_con.execute("SET memory_limit = '512MB'")
                except Exception:
                    new_con.close()
                    raise
                _con = new_con
                logger.info("Agent tools: DuckDB connection opened (read-only, 512MB limit): %s", DB_PATH)
    return _con.cursor()


def close_connection() -> None:
    """Close the shared connection. Call on process shutdown."""
    global _con
    with _lock:
        if _con is not None:
            _con.close()
            _con = None
            logger.info("Agent tools: DuckDB connection closed")
