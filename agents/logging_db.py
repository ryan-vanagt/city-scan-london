"""
DuckDB logging for agent interactions.

Uses short-lived read-write connections for each write operation.
DuckDB in-process does not allow read-only and read-write connections
to the same file simultaneously, so we open-write-close for each log
entry rather than holding a persistent write connection.

Only writes to agent_logs and bulletin_logs — never touches gold_scores or silver_metrics.
"""

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)

# Serialises all DuckDB write operations to prevent concurrent write conflicts
_write_lock = threading.Lock()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DB_PATH = str(PROJECT_ROOT / "data" / "agent_logs.duckdb")


def ensure_agent_logs_table() -> None:
    """Create agent_logs table if it does not exist.

    Opens a short-lived read-write connection. Call before opening
    any long-lived read-only connections (i.e. before api.db.open_connection).
    """
    con = duckdb.connect(LOG_DB_PATH)
    try:
        con.execute("""
            CREATE TABLE IF NOT EXISTS agent_logs (
                id              TEXT PRIMARY KEY,
                timestamp       TEXT NOT NULL,
                query           TEXT NOT NULL,
                tools_called    TEXT,
                tool_inputs     TEXT,
                tool_outputs    TEXT,
                sources_cited   TEXT,
                final_response  TEXT,
                latency_ms      INTEGER,
                model_used      TEXT
            )
        """)
        logger.info("agent_logs table ensured")
    finally:
        con.close()


def log_agent_interaction(
    *,
    query: str,
    tools_called: list[str],
    tool_inputs: list[dict],
    tool_outputs: list[dict],
    sources_cited: list[dict],
    final_response: str,
    latency_ms: int,
    model_used: str,
) -> None:
    """Insert a row into agent_logs. Fire-and-forget — never raises.

    Opens a short-lived read-write connection for the insert, then closes it
    immediately so it does not conflict with long-lived read-only connections.
    """
    try:
        with _write_lock:
            con = duckdb.connect(LOG_DB_PATH)
            try:
                con.execute(
                    """
                    INSERT INTO agent_logs
                    (id, timestamp, query, tools_called, tool_inputs,
                     tool_outputs, sources_cited, final_response, latency_ms, model_used)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        str(uuid.uuid4()),
                        datetime.now(timezone.utc).isoformat(),
                        query,
                        json.dumps(tools_called),
                        json.dumps(tool_inputs),
                        json.dumps(tool_outputs),
                        json.dumps(sources_cited),
                        final_response,
                        latency_ms,
                        model_used,
                    ],
                )
            finally:
                con.close()
    except Exception:
        logger.exception("Failed to log agent interaction")


def ensure_bulletin_logs_table() -> None:
    """Create bulletin_logs table if it does not exist."""
    con = duckdb.connect(LOG_DB_PATH)
    try:
        con.execute("""
            CREATE TABLE IF NOT EXISTS bulletin_logs (
                id              TEXT PRIMARY KEY,
                timestamp       TEXT NOT NULL,
                trigger         TEXT,
                scores_used     TEXT,
                headlines_used  TEXT,
                output_path     TEXT,
                latency_ms      INTEGER
            )
        """)
        logger.info("bulletin_logs table ensured")
    finally:
        con.close()


def log_bulletin(
    *,
    trigger: str,
    scores_used: dict,
    headlines_used: list[dict],
    output_path: str,
    latency_ms: int,
) -> None:
    """Insert a row into bulletin_logs. Fire-and-forget — never raises."""
    try:
        with _write_lock:
            con = duckdb.connect(LOG_DB_PATH)
            try:
                con.execute(
                    """
                    INSERT INTO bulletin_logs
                    (id, timestamp, trigger, scores_used, headlines_used,
                     output_path, latency_ms)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        str(uuid.uuid4()),
                        datetime.now(timezone.utc).isoformat(),
                        trigger,
                        json.dumps(scores_used),
                        json.dumps(headlines_used),
                        output_path,
                        latency_ms,
                    ],
                )
            finally:
                con.close()
    except Exception:
        logger.exception("Failed to log bulletin generation")
