"""
Gold layer aggregator.

Reads Silver metrics from DuckDB, computes weighted composite health scores
per borough per cycle, writes to the DuckDB gold_scores table, and embeds
each row as a text description in ChromaDB for RAG retrieval.
Schema: (borough_code, borough_name, timestamp, air_score, transit_score,
         sentiment_score, crime_score, composite_score, ingested_at, pipeline_stage)
"""
