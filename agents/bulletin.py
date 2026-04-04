"""
Bulletin Agent — LangChain prompt chain.

Generates a structured daily city health digest. Triggered by APScheduler
(daily) and on-demand via POST /bulletin/generate.

Chain:
  1. Fetch current Gold scores for all boroughs (direct DuckDB query)
  2. Query DuckDB for top 3 notable trends this week
  3. Fetch latest Guardian headlines (headline + URL only)
  4. Synthesise into markdown bulletin with cited sources

Output saved to /data/bulletins/YYYY-MM-DD.md.
Every run logged to the bulletin_logs DuckDB table.
"""
