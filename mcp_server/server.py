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
