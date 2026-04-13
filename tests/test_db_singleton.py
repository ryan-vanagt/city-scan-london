"""Test agents/tools/db.py — lazy singleton connection."""

import duckdb
import pytest

from agents.tools.db import close_connection, get_connection


@pytest.fixture(autouse=True)
def _cleanup_singleton():
    """Ensure the singleton connection is closed after each test."""
    yield
    close_connection()


def test_get_connection_returns_same_object():
    """Singleton should return the same connection on repeated calls."""
    con1 = get_connection()
    con2 = get_connection()
    assert con1 is con2


def test_get_connection_is_read_only():
    """Connection should be read-only — CREATE TABLE must be rejected."""
    con = get_connection()
    with pytest.raises(duckdb.InvalidInputException, match="[Rr]ead.only"):
        con.execute("CREATE TABLE _test_write_check (id INT)")
