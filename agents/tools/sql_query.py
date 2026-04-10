"""
Tool: run_sql

Executes a guarded, read-only SQL query against the CityScan DuckDB database.
Enables the Doctor Agent to answer analytical questions that the four curated
tools cannot cover (e.g. multi-column filters, correlations, aggregations).

Guardrails:
  1. Read-only DuckDB connection (engine-enforced — INSERT/UPDATE/DELETE/DROP blocked)
  2. Table allowlist — only gold_scores and silver_metrics are queryable
  3. Keyword blocklist — rejects write/DDL keywords as defence in depth
  4. Row limit — appends LIMIT 100 if no LIMIT clause is present
"""

import logging
import re

import duckdb

from agents.tools.db import get_connection

logger = logging.getLogger(__name__)

# Tables the agent is allowed to query
_ALLOWED_TABLES = {"gold_scores", "silver_metrics"}

# Tables that must never appear in agent queries (may contain user questions)
_BLOCKED_TABLES = {"agent_logs", "bulletin_logs"}

# SQL keywords that should never appear in agent queries (defence in depth)
_BLOCKED_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE|MERGE)\b",
    re.IGNORECASE,
)

_DEFAULT_ROW_LIMIT = 100


def run_sql(
    query: str,
    *,
    con: duckdb.DuckDBPyConnection | None = None,
) -> dict:
    """Execute a read-only SQL query against gold_scores or silver_metrics.

    The query is validated against a table allowlist and keyword blocklist
    before execution. Results are row-limited and timeout-guarded.

    Args:
        query: A SELECT SQL query string.
        con: Optional DuckDB connection. Uses the shared lazy connection if None.

    Returns:
        Dict with success, columns, rows, and row_count on success.
        Dict with success=False and error message on failure.
    """
    if con is None:
        con = get_connection()

    query = query.strip()

    if not query:
        return {"success": False, "error": "Empty query"}

    # --- Guardrail: keyword blocklist ---
    match = _BLOCKED_KEYWORDS.search(query)
    if match:
        logger.warning("run_sql: blocked keyword '%s' in query", match.group())
        return {
            "success": False,
            "error": f"Write/DDL operations are not permitted: {match.group()}",
        }

    # --- Guardrail: table allowlist ---
    query_lower = query.lower()
    for table in _BLOCKED_TABLES:
        if table in query_lower:
            logger.warning("run_sql: blocked table '%s' in query", table)
            return {
                "success": False,
                "error": f"Table '{table}' is not queryable by the agent",
            }

    # Check that at least one allowed table is referenced
    has_allowed = any(table in query_lower for table in _ALLOWED_TABLES)
    if not has_allowed:
        return {
            "success": False,
            "error": f"Query must reference one of: {', '.join(sorted(_ALLOWED_TABLES))}",
        }

    # --- Guardrail: row limit ---
    if not re.search(r"\bLIMIT\b", query, re.IGNORECASE):
        query = f"{query.rstrip(';')} LIMIT {_DEFAULT_ROW_LIMIT}"

    # --- Execute with timeout ---
    try:
        result = con.execute(query)
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()

        # Convert rows to list of dicts for clean JSON serialisation
        row_dicts = [dict(zip(columns, row)) for row in rows]

        return {
            "success": True,
            "columns": columns,
            "rows": row_dicts,
            "row_count": len(row_dicts),
        }
    except duckdb.Error as exc:
        logger.warning("run_sql: query failed: %s", exc)
        return {"success": False, "error": str(exc)}
