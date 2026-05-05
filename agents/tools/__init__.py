"""
Agent tools package.

Eleven tools across two categories — core query functions (no framework
dependency) and LangGraph @tool wrappers used by the Doctor agent's
ToolNode. The MCP server imports the core functions directly.

Core query functions:
    # 4 curated DuckDB readers + 1 guarded SQL + 1 RAG
    from agents.tools.health_score import get_london_score
    from agents.tools.borough_query import get_borough_health, compare_boroughs
    from agents.tools.trend_analysis import get_trend
    from agents.tools.sql_query import run_sql
    from agents.tools.rag_query import search_scores

    # 5 static-JSON overlays (no DuckDB dependency)
    from agents.tools.deprivation import get_deprivation                 # IMD 2025
    from agents.tools.score_quality import get_score_quality             # bootstrap CIs + flags
    from agents.tools.housing_affordability import get_housing_affordability  # ONS 2025
    from agents.tools.health_index import get_health_index               # ONS Health Index 2021
    from agents.tools.transit_access import get_transit_access           # TfL PTAL 2015

LangGraph @tool wrappers (requires langchain_core):
    from agents.tools.langchain_tools import ALL_TOOLS
"""
