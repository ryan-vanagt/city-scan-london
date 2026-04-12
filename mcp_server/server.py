"""
CityScan MCP Server.

Exposes all six Doctor agent tools as a Model Context Protocol (MCP) server,
allowing any MCP-compatible client (Claude Desktop, other agents) to query
CityScan data directly without going through the FastAPI REST layer.

Tools exposed:
  - get_borough_health(borough)
  - get_london_score()
  - get_trend(borough, metric, days)
  - compare_boroughs(metric, top_n, ascending)
  - run_sql(query)
  - search_scores(query, n_results, borough_code)
"""

import atexit
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Resolve project root so imports work from any working directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

from mcp.server.fastmcp import FastMCP  # noqa: E402

from agents.tools.borough_query import compare_boroughs as _compare_boroughs  # noqa: E402
from agents.tools.borough_query import get_borough_health as _get_borough_health  # noqa: E402
from agents.tools.db import close_connection  # noqa: E402
from agents.tools.health_score import get_london_score as _get_london_score  # noqa: E402
from agents.tools.rag_query import search_scores as _search_scores  # noqa: E402
from agents.tools.sql_query import run_sql as _run_sql  # noqa: E402
from agents.tools.trend_analysis import get_trend as _get_trend  # noqa: E402

# Clean up DuckDB connection on process exit
atexit.register(close_connection)

try:
    MCP_PORT = int(os.environ.get("MCP_PORT", "8002"))
except ValueError:
    logger.warning("Invalid MCP_PORT value, falling back to 8002")
    MCP_PORT = 8002

# Default to localhost; Docker sets MCP_HOST=0.0.0.0 for container networking
MCP_HOST = os.environ.get("MCP_HOST", "127.0.0.1")

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
        return json.dumps(_get_london_score(), default=str)
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
        return json.dumps(_get_borough_health(borough), default=str)
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
        return json.dumps(_compare_boroughs(metric, top_n, ascending), default=str)
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
        return json.dumps(_get_trend(borough, metric, days), default=str)
    except Exception as exc:
        logger.error("MCP get_trend failed: %s", exc)
        return json.dumps({"error": "Internal error"})


@mcp.tool(
    name="run_sql",
    description="Execute a guarded read-only SQL query against gold_scores or silver_metrics.",
)
def tool_run_sql(query: str) -> str:
    """Run a SELECT query. Write operations and metadata tables are blocked."""
    try:
        if len(query) > 10_000:
            return json.dumps({"error": "Query too long (max 10000 characters)"})
        return json.dumps(_run_sql(query), default=str)
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


if __name__ == "__main__":
    logger.info("Starting CityScan MCP server on port %d (streamable-http)", MCP_PORT)
    mcp.run(transport="streamable-http")
