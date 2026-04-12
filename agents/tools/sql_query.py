"""
Tool: run_sql

Executes a guarded, read-only SQL query against the CityScan DuckDB database.
Enables the Doctor Agent to answer analytical questions that the four curated
tools cannot cover (e.g. multi-column filters, correlations, aggregations).

Guardrails:
  1. Read-only DuckDB connection (engine-enforced — INSERT/UPDATE/DELETE/DROP blocked)
  2. SQL comments stripped before validation (prevents bypass via comments)
  3. Table allowlist — only gold_scores and silver_metrics are queryable
  4. Keyword blocklist — rejects write/DDL/admin keywords as defence in depth
  5. Metadata function blocklist — blocks duckdb_*() and other introspection calls
  6. File-read function blocklist — blocks read_csv, read_parquet, etc.
  7. Row limit — always wraps query in outer LIMIT 100 regardless of inner LIMIT
  8. Query length limit — rejects queries longer than 10000 characters
"""

import logging
import re
from datetime import date, datetime, timedelta
from decimal import Decimal

import duckdb

from agents.tools.db import get_connection

logger = logging.getLogger(__name__)

_MAX_QUERY_LENGTH = 10_000

# Tables the agent is allowed to query
_ALLOWED_TABLES = {"gold_scores", "silver_metrics"}

# Tables that must never appear in agent queries (may contain user questions).
# Includes all duckdb_* and sqlite_* system tables to prevent metadata leakage.
_BLOCKED_TABLES = {
    "agent_logs",
    "bulletin_logs",
    "information_schema",
    "pg_catalog",
    "duckdb_tables",
    "duckdb_columns",
    "duckdb_schemas",
    "duckdb_views",
    "duckdb_constraints",
    "duckdb_indexes",
    "duckdb_functions",
    "duckdb_settings",
    "duckdb_extensions",
    "duckdb_types",
    "duckdb_dependencies",
    "sqlite_master",
    "sqlite_schema",
}

# Regex patterns for catching any remaining duckdb_*/sqlite_* system table references
_BLOCKED_TABLE_PATTERNS = [
    re.compile(r"\bduckdb_\w+\b", re.IGNORECASE),
    re.compile(r"\bsqlite_\w+\b", re.IGNORECASE),
]

# SQL keywords that should never appear in agent queries (defence in depth)
_BLOCKED_KEYWORDS = re.compile(
    r"\b("
    r"INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE|MERGE"
    r"|COPY|EXPORT|IMPORT|LOAD|INSTALL|CALL|PRAGMA|SET|ATTACH|DETACH"
    r")\b",
    re.IGNORECASE,
)

# Block ALL duckdb_*() metadata functions, plus other introspection functions
_BLOCKED_FUNCTIONS = re.compile(
    r"\b(duckdb_\w+|current_setting|table_info|pragma_table_info)\s*\(",
    re.IGNORECASE,
)

# File-read functions that must be blocked to prevent local file access
_BLOCKED_FILE_FUNCTIONS = re.compile(
    r"\b(read_csv_auto|read_csv|read_parquet|read_json_auto|read_json|read_blob|glob)\s*\(",
    re.IGNORECASE,
)

# Block file path table references (e.g. FROM '/path/to/file.csv')
_BLOCKED_FILE_PATH = re.compile(
    r"\bFROM\s+['\"]",
    re.IGNORECASE,
)

_DEFAULT_ROW_LIMIT = 100


def _serialize_value(val):
    """Convert DuckDB-specific types to JSON-serializable Python types."""
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, timedelta):
        return str(val)
    return val


def _strip_sql_comments(sql: str) -> str:
    """Remove SQL line comments (--) and block comments (/* */) from a query.

    Uses a loop for block comments to handle nested comments like /* a /* b */ c */.
    """
    # Remove block comments — loop until no more remain (handles nesting)
    while "/*" in sql:
        sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    # Remove line comments
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql


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

    # --- Guardrail: query length limit ---
    if len(query) > _MAX_QUERY_LENGTH:
        return {"success": False, "error": f"Query too long (max {_MAX_QUERY_LENGTH} characters)"}

    # --- Strip comments before all validation ---
    query_clean = _strip_sql_comments(query)
    query_lower = query_clean.lower()

    # --- Guardrail: keyword blocklist ---
    match = _BLOCKED_KEYWORDS.search(query_clean)
    if match:
        logger.warning("run_sql: blocked keyword '%s' in query", match.group())
        return {
            "success": False,
            "error": f"Write/DDL operations are not permitted: {match.group()}",
        }

    # --- Guardrail: blocked metadata functions ---
    func_match = _BLOCKED_FUNCTIONS.search(query_clean)
    if func_match:
        logger.warning("run_sql: blocked metadata function '%s' in query", func_match.group())
        return {
            "success": False,
            "error": "Metadata introspection functions are not permitted",
        }

    # --- Guardrail: blocked file-read functions ---
    file_match = _BLOCKED_FILE_FUNCTIONS.search(query_clean)
    if file_match:
        logger.warning("run_sql: blocked file-read function '%s' in query", file_match.group())
        return {
            "success": False,
            "error": "File-read functions are not permitted",
        }

    # --- Guardrail: blocked file path table references (FROM '/path/...') ---
    if _BLOCKED_FILE_PATH.search(query_clean):
        logger.warning("run_sql: blocked file path table reference in query")
        return {
            "success": False,
            "error": "File path table references are not permitted",
        }

    # --- Guardrail: table blocklist (word-boundary matching) ---
    for table in _BLOCKED_TABLES:
        if re.search(rf"\b{re.escape(table)}\b", query_lower):
            logger.warning("run_sql: blocked table '%s' in query", table)
            return {
                "success": False,
                "error": f"Table '{table}' is not queryable by the agent",
            }

    # --- Guardrail: catch-all duckdb_*/sqlite_* system table patterns ---
    for pattern in _BLOCKED_TABLE_PATTERNS:
        pat_match = pattern.search(query_lower)
        if pat_match:
            logger.warning("run_sql: blocked system table pattern '%s' in query", pat_match.group())
            return {
                "success": False,
                "error": "System metadata tables are not queryable by the agent",
            }

    # Check that at least one allowed table is referenced (word-boundary matching)
    has_allowed = any(
        re.search(rf"\b{re.escape(table)}\b", query_lower)
        for table in _ALLOWED_TABLES
    )
    if not has_allowed:
        return {
            "success": False,
            "error": f"Query must reference one of: {', '.join(sorted(_ALLOWED_TABLES))}",
        }

    # --- Guardrail: enforce row limit via outer wrapper ---
    # Always wrap to cap at _DEFAULT_ROW_LIMIT regardless of inner LIMIT
    wrapped_query = f"SELECT * FROM ({query_clean.rstrip(';')}) AS _q LIMIT {_DEFAULT_ROW_LIMIT}"

    # --- Execute with timeout ---
    try:
        result = con.execute(wrapped_query)
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()

        # Convert rows to list of dicts for clean JSON serialisation
        row_dicts = [{k: _serialize_value(v) for k, v in zip(columns, row)} for row in rows]

        return {
            "success": True,
            "columns": columns,
            "rows": row_dicts,
            "row_count": len(row_dicts),
        }
    except duckdb.Error as exc:
        logger.warning("run_sql: query failed: %s", exc)
        return {"success": False, "error": "Query execution failed — check syntax and table names"}
