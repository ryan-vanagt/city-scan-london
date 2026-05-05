"""
CityScan MCP Server.

Exposes all eleven Doctor agent tools as a Model Context Protocol (MCP)
server, allowing any MCP-compatible client (Claude Desktop, other agents)
to query CityScan data directly without going through the FastAPI REST
layer.

Tools exposed:
  - get_borough_health(borough)
  - get_london_score()
  - get_trend(borough, metric, days)
  - compare_boroughs(metric, top_n, ascending)
  - run_sql(query)
  - search_scores(query, n_results, borough_code)
  - get_deprivation(borough)             — IMD 2025 rank + 7 sub-domains
  - get_score_quality(borough)           — per-organ data-quality flags + CIs
  - get_housing_affordability(borough)   — ONS Housing Affordability Ratio 2025
  - get_health_index(borough)            — ONS Health Index 2021 (validation)
  - get_transit_access(borough)          — TfL PTAL 2015 (SDG 11.2)
"""

# Security: no authentication. Relies on MCP_HOST binding (default 127.0.0.1).
# Set MCP_HOST=0.0.0.0 only in Docker with network isolation.

import json
import logging
import os
import sys
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv

# Resolve project root so imports work from any working directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

import duckdb  # noqa: E402

from mcp.server.fastmcp import FastMCP  # noqa: E402

from agents.tools.borough_query import compare_boroughs as _compare_boroughs  # noqa: E402
from agents.tools.borough_query import get_borough_health as _get_borough_health  # noqa: E402
from agents.tools.deprivation import get_deprivation as _get_deprivation  # noqa: E402
from agents.tools.health_index import get_health_index as _get_health_index  # noqa: E402
from agents.tools.health_score import get_london_score as _get_london_score  # noqa: E402
from agents.tools.housing_affordability import get_housing_affordability as _get_housing_affordability  # noqa: E402
from agents.tools.rag_query import search_scores as _search_scores  # noqa: E402
from agents.tools.score_quality import get_score_quality as _get_score_quality  # noqa: E402
from agents.tools.sql_query import run_sql as _run_sql  # noqa: E402
from agents.tools.transit_access import get_transit_access as _get_transit_access  # noqa: E402
from agents.tools.trend_analysis import get_trend as _get_trend  # noqa: E402

DB_PATH = str(PROJECT_ROOT / "data" / "cityscan.duckdb")


@contextmanager
def _db_connection():
    """Open a fresh read-only DuckDB connection, closed after use.

    Avoids holding a persistent lock on cityscan.duckdb so the ingestion
    service can acquire write locks without cross-container contention.
    """
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        yield con
    finally:
        con.close()

try:
    MCP_PORT = int(os.environ.get("MCP_PORT", "8002"))
except ValueError:
    logger.warning("Invalid MCP_PORT value, falling back to 8002")
    MCP_PORT = 8002

# Default to localhost; Docker sets MCP_HOST=0.0.0.0 for container networking
MCP_HOST = os.environ.get("MCP_HOST", "127.0.0.1")

# Security: MCP server relies on network-level access control. In local dev,
# MCP_HOST=127.0.0.1 makes the server only reachable from the host. In Docker
# the container binds to 0.0.0.0 but the compose file maps only
# 127.0.0.1:8002:8002 to the host, so external callers cannot reach it. If a
# future typo ever widens that host binding, MCP_AUTH_TOKEN is the safety net.
# We WARN loudly when a non-loopback bind is requested without a token instead
# of refusing to start — a startup-time crash in production would be worse
# than the defense-in-depth gap we're trying to close.
MCP_AUTH_TOKEN = os.environ.get("MCP_AUTH_TOKEN", "")
if MCP_HOST not in ("127.0.0.1", "localhost", "::1") and not MCP_AUTH_TOKEN:
    logger.warning(
        "MCP security: MCP_HOST=%s but MCP_AUTH_TOKEN is unset. If the host-side "
        "port binding is ever changed from 127.0.0.1 to 0.0.0.0, run_sql and the "
        "other MCP tools would be reachable without authentication. Set "
        "MCP_AUTH_TOKEN to close this gap.",
        MCP_HOST,
    )
elif MCP_AUTH_TOKEN:
    logger.info("MCP security: MCP_AUTH_TOKEN set")
else:
    logger.info("MCP security: network-level access control (loopback binding)")

mcp = FastMCP(
    name="CityScan London",
    instructions=(
        "Query London's city health data — scores, trends, borough comparisons, "
        "SQL, and semantic search. All scores are 0-100 where 100 = healthiest."
    ),
    host=MCP_HOST,
    port=MCP_PORT,
)


@mcp.tool(
    name="get_london_score",
    description="Get the current city-wide average health scores across all 33 London boroughs.",
)
def tool_get_london_score() -> str:
    """Return London-wide composite and sub-scores."""
    try:
        with _db_connection() as con:
            return json.dumps(_get_london_score(con=con), default=str)
    except Exception as exc:
        logger.error("MCP get_london_score failed: %s", exc)
        return json.dumps({"error": "Internal error"})


@mcp.tool(
    name="get_borough_health",
    description="Get the full health score breakdown for a single London borough.",
)
def tool_get_borough_health(borough: str) -> str:
    """Return all scores for one borough. Accepts name (e.g. 'Camden') or ONS code (e.g. 'E09000007')."""
    try:
        borough = borough[:100]
        with _db_connection() as con:
            return json.dumps(_get_borough_health(borough, con=con), default=str)
    except Exception as exc:
        logger.error("MCP get_borough_health failed: %s", exc)
        return json.dumps({"error": "Internal error"})


@mcp.tool(
    name="compare_boroughs",
    description="Rank London boroughs by a health metric and return the top N.",
)
def tool_compare_boroughs(
    metric: str = "composite_score",
    top_n: int = 5,
    ascending: bool = False,
) -> str:
    """Compare boroughs by metric. Valid metrics: air_score, transit_score, sentiment_score, immune_score, composite_score."""
    try:
        top_n = max(1, min(top_n, 33))
        with _db_connection() as con:
            return json.dumps(_compare_boroughs(metric, top_n, ascending, con=con), default=str)
    except Exception as exc:
        logger.error("MCP compare_boroughs failed: %s", exc)
        return json.dumps({"error": "Internal error"})


@mcp.tool(
    name="get_trend",
    description="Get the trend direction and score delta for a borough over recent days.",
)
def tool_get_trend(
    borough: str,
    metric: str = "composite_score",
    days: int = 7,
) -> str:
    """Trend analysis for a borough. Returns direction (improving/declining/stable) and delta."""
    try:
        borough = borough[:100]
        with _db_connection() as con:
            return json.dumps(_get_trend(borough, metric, days, con=con), default=str)
    except Exception as exc:
        logger.error("MCP get_trend failed: %s", exc)
        return json.dumps({"error": "Internal error"})


@mcp.tool(
    name="run_sql",
    description="Execute a guarded read-only SQL query against gold_scores, silver_metrics, silver_detail, or silver_headlines.",
)
def tool_run_sql(query: str) -> str:
    """Run a SELECT query. Write operations and metadata tables are blocked."""
    try:
        if len(query) > 10_000:
            return json.dumps({"error": "Query too long (max 10000 characters)"})
        with _db_connection() as con:
            return json.dumps(_run_sql(query, con=con), default=str)
    except Exception as exc:
        logger.error("MCP run_sql failed: %s", exc)
        return json.dumps({"error": "Internal error"})


@mcp.tool(
    name="search_scores",
    description="Semantic search over borough health score embeddings using ChromaDB.",
)
def tool_search_scores(
    query: str,
    n_results: int = 5,
    borough_code: str | None = None,
) -> str:
    """Search for relevant borough health data by natural language query."""
    try:
        query = query[:1000]
        return json.dumps(_search_scores(query, n_results, borough_code), default=str)
    except Exception as exc:
        logger.error("MCP search_scores failed: %s", exc)
        return json.dumps({"error": "Internal error"})


@mcp.tool(
    name="get_deprivation",
    description="Get IMD 2025 deprivation rank (1-296 nationally) and 7 domain sub-scores for a London borough.",
)
def tool_get_deprivation(borough: str) -> str:
    """IMD 2025 rank + sub-domains. Accepts name or ONS code."""
    try:
        borough = str(borough)[:100]
        return json.dumps(_get_deprivation(borough), default=str)
    except Exception as exc:
        logger.error("MCP get_deprivation failed: %s", exc)
        return json.dumps({"error": "Internal error"})


@mcp.tool(
    name="get_score_quality",
    description="Get per-organ data-quality flags (green/amber/red) and 95% bootstrap CIs for a borough's recent scores.",
)
def tool_get_score_quality(borough: str) -> str:
    """Per-organ reliability flags + bootstrap CIs. Call before quoting an organ score."""
    try:
        borough = str(borough)[:100]
        return json.dumps(_get_score_quality(borough), default=str)
    except Exception as exc:
        logger.error("MCP get_score_quality failed: %s", exc)
        return json.dumps({"error": "Internal error"})


@mcp.tool(
    name="get_housing_affordability",
    description="Get the ONS Housing Affordability Ratio (median price ÷ median earnings) for a borough or all 33.",
)
def tool_get_housing_affordability(borough: str = "") -> str:
    """Housing affordability ratio. Empty string returns all 33 boroughs sorted desc."""
    try:
        borough = str(borough)[:100] if borough else ""
        return json.dumps(_get_housing_affordability(borough or None), default=str)
    except Exception as exc:
        logger.error("MCP get_housing_affordability failed: %s", exc)
        return json.dumps({"error": "Internal error"})


@mcp.tool(
    name="get_health_index",
    description="Get the ONS Health Index 2021 score for a London borough (UK official subnational health composite).",
)
def tool_get_health_index(borough: str) -> str:
    """ONS Health Index 2021. Independent benchmark for CityScan validation. City of London excluded by ONS convention."""
    try:
        borough = str(borough)[:100]
        return json.dumps(_get_health_index(borough), default=str)
    except Exception as exc:
        logger.error("MCP get_health_index failed: %s", exc)
        return json.dumps({"error": "Internal error"})


@mcp.tool(
    name="get_transit_access",
    description="Get the TfL PTAL 2015 transit-access band (1a-6b) for a London borough — the SDG 11.2 access measure.",
)
def tool_get_transit_access(borough: str) -> str:
    """PTAL 2015 borough average. Distinct from live transit_score (line reliability)."""
    try:
        borough = str(borough)[:100]
        return json.dumps(_get_transit_access(borough), default=str)
    except Exception as exc:
        logger.error("MCP get_transit_access failed: %s", exc)
        return json.dumps({"error": "Internal error"})


if __name__ == "__main__":
    logger.info("Starting CityScan MCP server on port %d (streamable-http)", MCP_PORT)
    mcp.run(transport="streamable-http")
