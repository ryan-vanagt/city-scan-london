"""
Agent tools package.

Core query functions (no framework dependency):
    from agents.tools.health_score import get_london_score
    from agents.tools.borough_query import get_borough_health, compare_boroughs
    from agents.tools.trend_analysis import get_trend
    from agents.tools.sql_query import run_sql
    from agents.tools.rag_query import search_scores

LangGraph @tool wrappers (requires langchain_core):
    from agents.tools.langchain_tools import ALL_TOOLS
"""
