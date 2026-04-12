"""Test agents/logging_db.py — table creation, row insertion, error handling."""

import duckdb
import pytest

from agents.logging_db import (
    ensure_agent_logs_table,
    ensure_bulletin_logs_table,
    log_agent_interaction,
    log_bulletin,
)


@pytest.fixture
def log_db(tmp_path, monkeypatch):
    """Provide a temporary DuckDB for logging tests."""
    db_path = str(tmp_path / "test_agent_logs.duckdb")
    monkeypatch.setattr("agents.logging_db.LOG_DB_PATH", db_path)
    return db_path


def test_ensure_agent_logs_table_creates_table(log_db):
    ensure_agent_logs_table()
    con = duckdb.connect(log_db, read_only=True)
    tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
    con.close()
    assert "agent_logs" in tables


def test_ensure_bulletin_logs_table_creates_table(log_db):
    ensure_bulletin_logs_table()
    con = duckdb.connect(log_db, read_only=True)
    tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
    con.close()
    assert "bulletin_logs" in tables


def test_log_agent_interaction_inserts_row(log_db):
    ensure_agent_logs_table()
    log_agent_interaction(
        query="How is London?",
        tools_called=["get_london_score"],
        tool_inputs=[{"get_london_score": {}}],
        tool_outputs=[{"get_london_score": {"composite_score": 65}}],
        sources_cited=[{"type": "duckdb", "tool": "get_london_score"}],
        final_response="London is doing well.",
        latency_ms=1200,
        model_used="claude-haiku-4-5",
    )
    con = duckdb.connect(log_db, read_only=True)
    count = con.execute("SELECT COUNT(*) FROM agent_logs").fetchone()[0]
    con.close()
    assert count == 1


def test_log_bulletin_inserts_row(log_db):
    ensure_bulletin_logs_table()
    log_bulletin(
        trigger="manual",
        scores_used={"composite": 65},
        headlines_used=[{"title": "Test headline"}],
        output_path="/data/bulletins/2026-04-12.md",
        latency_ms=3000,
    )
    con = duckdb.connect(log_db, read_only=True)
    count = con.execute("SELECT COUNT(*) FROM bulletin_logs").fetchone()[0]
    con.close()
    assert count == 1


def test_log_agent_interaction_is_fire_and_forget(log_db, monkeypatch):
    """Logging should not raise even if the DB write fails."""
    ensure_agent_logs_table()
    # Corrupt the path so writes fail
    monkeypatch.setattr("agents.logging_db.LOG_DB_PATH", "/nonexistent/path/db.duckdb")
    # Should not raise
    log_agent_interaction(
        query="test",
        tools_called=[],
        tool_inputs=[],
        tool_outputs=[],
        sources_cited=[],
        final_response="test",
        latency_ms=0,
        model_used="test",
    )
