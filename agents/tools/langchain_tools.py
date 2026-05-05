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
from agents.tools.deprivation import get_deprivation
from agents.tools.health_index import get_health_index
from agents.tools.health_score import get_london_score
from agents.tools.housing_affordability import get_housing_affordability
from agents.tools.rag_query import search_scores
from agents.tools.score_quality import get_score_quality
from agents.tools.sql_query import run_sql
from agents.tools.transit_access import get_transit_access
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
        metric: One of air_score, air_quality_modelled_score, transit_score,
            sentiment_score, immune_score, green_space_score,
            green_space_access_score, composite_score.
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
        metric: One of air_score, air_quality_modelled_score, transit_score,
            sentiment_score, immune_score, green_space_score,
            green_space_access_score, composite_score.
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
        air_quality_modelled_score, transit_score, sentiment_score,
        immune_score, green_space_score, green_space_access_score,
        composite_score, ingested_at, pipeline_stage
        (air_score = live OpenAQ readings, PM2.5 and/or NO2 depending on
         station, ~24/33 borough coverage, updates each cycle.
         air_quality_modelled_score = LAEI 2022 GLA
         modelled population-weighted annual mean, 33/33 coverage, yearly
         static — use for equity analysis and cross-borough comparison.
         green_space_score = raw GLA green cover %, min-max normalised 0-100.
         green_space_access_score = same cover but weighted by ward-level
         residential population, so low-residential wards like Hyde Park in
         Westminster contribute less; use this when comparing equitable access
         to green space.)
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


@tool
def get_deprivation_tool(borough: str) -> dict:
    """Get IMD 2025 deprivation data for a London borough.

    Returns the UK government's Index of Multiple Deprivation rank (1-296,
    where 1 is most deprived nationally) plus 7 domain sub-scores:
    income, employment, education, health, crime, barriers to housing,
    living environment.

    Use this to understand a borough's structural context — long-term
    disadvantage that live health scores don't capture. Compare IMD domains
    against CityScan organ scores (e.g. IMD Crime vs live immune score).

    Args:
        borough: Borough name (e.g. 'Hackney') or ONS code (e.g. 'E09000012').
    """
    borough = borough[:100]
    return get_deprivation(borough)


@tool
def get_score_quality_tool(borough: str) -> dict:
    """Get per-organ data-quality flags + 95% bootstrap CIs for a London borough.

    Returns each organ's reliability flag (green = stable bootstrap CI, amber
    = wide CI / static-cadence / non-borough-specific signal, red = sparse
    underlying data) plus the bootstrap CI numbers and any disclosure note.

    **Call this BEFORE quoting an organ score with confidence.** If the flag
    is amber or red for the relevant organ, prepend a brief reliability
    caveat in the response (e.g. "based on a sparse sensor signal" /
    "London-wide proxy" / "annual snapshot"). Do not present a borough's
    score as authoritative when its flag is red.

    Args:
        borough: Borough name (e.g. 'Hackney') or ONS code (e.g. 'E09000012').
    """
    borough = borough[:100]
    return get_score_quality(borough)


@tool
def get_housing_affordability_tool(borough: str = "") -> dict:
    """Get the ONS Housing Affordability Ratio for a London borough or all 33.

    The ratio is median house price ÷ median workplace-based annual earnings.
    Higher = less affordable. London-specific structural stressor.

    Use this for housing-stress questions in preference to IMD's barriers
    domain — it is more London-specific and easier to interpret. Pair with
    composite or immune scores to surface compound stress (expensive AND
    high-stress boroughs).

    Args:
        borough: Borough name or ONS code. Pass empty string to get all 33
            boroughs sorted by ratio descending (most expensive first).
    """
    borough = borough[:100] if borough else ""
    return get_housing_affordability(borough or None)


@tool
def get_transit_access_tool(borough: str) -> dict:
    """Get the TfL PTAL (Public Transport Accessibility Level) for a London borough.

    PTAL is the canonical transport-access measure used by the GLA, TfL,
    and Cabinet Office for SDG 11.2 (access to safe, affordable,
    accessible, sustainable transport for all). Bands run 1a (very poor)
    to 6b (excellent). Distinct from `transit_score` (live tube line
    reliability) — use this for ACCESS questions ("who can reach
    transit?"), and `get_borough_health` for RELIABILITY questions ("are
    the trains running?").

    Vintage: 2015, the most recent publicly published borough-average
    edition. PTAL is structural; network geography is slow-moving. The
    2015 edition predates the Elizabeth Line (opened 2022), so it
    understates current access for boroughs the Elizabeth Line reaches:
    City of London (Liverpool Street, Farringdon), City of Westminster
    (Paddington, Bond Street), Camden (Tottenham Court Road), Tower
    Hamlets (Whitechapel, Canary Wharf), Newham (Stratford, Custom
    House), Greenwich (Woolwich), Redbridge (Ilford corridor), Havering
    (Romford), and parts of Ealing and Hillingdon. Disclose this when
    the user asks about those boroughs.

    Args:
        borough: Borough name (e.g. 'Hackney') or ONS code (e.g. 'E09000012').
    """
    borough = borough[:100]
    return get_transit_access(borough)


@tool
def get_health_index_tool(borough: str) -> dict:
    """Get the ONS Health Index for a London borough.

    The Health Index is the UK's official subnational health composite,
    built from inputs that DO NOT appear in CityScan's pipeline (life
    expectancy, mortality, mental-health prevalence, behaviours). This
    makes a comparison between CityScan's composite and the Health Index
    a convergent-validity reference, not a tautology.

    Use when the user asks how CityScan compares to the official health
    measure, or to triangulate borough-level findings against an external
    benchmark. England 2015 baseline = 100; higher = healthier.

    City of London is excluded from this dataset by ONS convention.

    Args:
        borough: Borough name (e.g. 'Hackney') or ONS code (e.g. 'E09000012').
    """
    borough = borough[:100]
    return get_health_index(borough)


ALL_TOOLS = [
    get_borough_health_tool,
    get_london_score_tool,
    get_trend_tool,
    compare_boroughs_tool,
    run_sql_tool,
    search_scores_tool,
    get_deprivation_tool,
    get_score_quality_tool,
    get_housing_affordability_tool,
    get_health_index_tool,
    get_transit_access_tool,
]
