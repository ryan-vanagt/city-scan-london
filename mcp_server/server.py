"""
CityScan MCP Server.

Exposes the four Doctor agent tools as a Model Context Protocol (MCP) server,
allowing any MCP-compatible client (Claude Desktop, other agents) to query
CityScan data directly without going through the FastAPI REST layer.

Tools exposed:
  - get_borough_health(borough_name, time_range)
  - get_london_score(timestamp)
  - get_trend(borough_name, metric, days)
  - compare_boroughs(metric, top_n)
"""
