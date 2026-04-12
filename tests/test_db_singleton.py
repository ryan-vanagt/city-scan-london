"""Test agents/tools/db.py — lazy singleton connection."""

import duckdb

from agents.tools.db import close_connection, get_connection


def test_get_connection_returns_same_object():
    """Singleton should return the same connection on repeated calls."""
    con1 = get_connection()
    con2 = get_connection()
    assert con1 is con2


def test_get_connection_is_read_only():
    """Connection should be read-only."""
    con = get_connection()
    # DuckDB read-only connections reject write operations
    try:
        con.execute("CREATE TABLE _test_write_check (id INT)")
        # If we get here, it's not read-only — fail
        con.execute("DROP TABLE _test_write_check")
        assert False, "Connection should be read-only but accepted a CREATE TABLE"
    except duckdb.Error:
        pass  # Expected — connection is read-only
