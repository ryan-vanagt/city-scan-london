"""
LangGraph @tool wrappers for the Doctor Agent's ToolNode.

Wraps the core query functions with LangChain's @tool decorator so
LangGraph can register them. The MCP server imports the core functions
directly from their respective modules — no LangChain dependency needed.

Usage:
    from agents.tools.langchain_tools import ALL_TOOLS
    tool_node = ToolNode(ALL_TOOLS)
"""

from langchain_core.tools import tool

from agents.tools.borough_query import get_borough_health, compare_boroughs
from agents.tools.health_score import get_london_score
from agents.tools.rag_query import search_scores
from agents.tools.sql_query import run_sql
from agents.tools.trend_analysis import get_trend


@tool
def get_borough_health_tool(borough: str) -> dict:
    """Get the current health score breakdown for a London borough.

    Returns air, transit, sentiment, immune, green_space, and composite
    scores (0-100, where 100 is healthiest). Accepts borough name
    (e.g. 'Camden', 'Hackney') or ONS code (e.g. 'E09000007').
    """
    borough = borough[:100]
    return get_borough_health(borough)


@tool
def get_london_score_tool() -> dict:
    """Get the overall London-wide health score averaged across all 33 boroughs.

    Returns composite and sub-scores (air, transit, sentiment, immune,
    green_space), the number of boroughs included, and the latest timestamp.
    """
    return get_london_score()


@tool
def get_trend_tool(
    borough: str,
    metric: str = "composite_score",
    days: int = 7,
) -> dict:
    """Get the score trend for a London borough over the last N days.

    Shows whether the borough is improving, declining, or stable, with
    the exact score delta. Use this to answer questions about change
    over time.

    Args:
        borough: Borough name or ONS code.
        metric: One of air_score, transit_score, sentiment_score,
            immune_score, green_space_score, composite_score.
        days: Lookback window, 1-30 (default 7).
    """
    borough = borough[:100]
    return get_trend(borough, metric, days)


@tool
def compare_boroughs_tool(
    metric: str = "composite_score",
    top_n: int = 5,
    ascending: bool = False,
) -> dict:
    """Rank London boroughs by a health metric.

    Use ascending=False (default) for best boroughs first (highest score).
    Use ascending=True for worst boroughs first (lowest score).

    Args:
        metric: One of air_score, transit_score, sentiment_score,
            immune_score, green_space_score, composite_score.
        top_n: Number of boroughs to return (1-33, default 5).
        ascending: Sort order. False=best first, True=worst first.
    """
    return compare_boroughs(metric, top_n, ascending)


@tool
def run_sql_tool(query: str) -> dict:
    """Run a read-only SQL query against the CityScan database.

    Use this tool ONLY when the other specialised tools cannot answer
    the question. Supports any SELECT query including aggregations,
    window functions, correlations, and multi-column filters.

    Available tables:
      - gold_scores: borough_code, borough_name, timestamp, air_score,
        transit_score, sentiment_score, immune_score, green_space_score,
        composite_score, ingested_at, pipeline_stage
      - silver_metrics: borough_code, borough_name, timestamp,
        metric_name, raw_value, normalised_score, source, ingested_at,
        pipeline_stage
      - silver_detail: borough_code, borough_name, timestamp, source,
        category, label, value, detail_text, ingested_at
        (Per-item context: crime categories, tube line statuses,
        AQ station readings, NHS trust performance.
        Always filter by source and borough_code in WHERE clause.)
      - silver_headlines: timestamp, source, title, url, sentiment_score,
        ingested_at
        (Individual news headlines with per-title sentiment.
        Always include a WHERE clause.)

    Results limited to 100 rows (50 for detail tables). Write operations blocked.

    Args:
        query: A SELECT SQL query string.
    """
    return run_sql(query)


@tool
def search_scores_tool(
    query: str,
    n_results: int = 5,
    borough_code: str | None = None,
) -> dict:
    """Search for borough health scores relevant to a natural language query.

    Uses semantic similarity over historical borough health descriptions
    stored in ChromaDB. Use this to find relevant context before answering
    questions about trends, comparisons, or historical patterns.

    Args:
        query: What to search for, e.g. 'worst air quality boroughs'
            or 'Camden health overview'.
        n_results: Number of results to return (1-20, default 5).
        borough_code: Optional ONS code to scope results to one borough.
    """
    return search_scores(query, n_results, borough_code)


ALL_TOOLS = [
    get_borough_health_tool,
    get_london_score_tool,
    get_trend_tool,
    compare_boroughs_tool,
    run_sql_tool,
    search_scores_tool,
]
