"""
Silver layer transformer.

Reads Bronze JSON files, parses and validates each source, maps to ONS borough codes,
normalises raw values to 0–100 scores, and writes to the DuckDB silver_metrics table.
Schema: (borough_code, borough_name, timestamp, metric_name, raw_value,
         normalised_score, source, ingested_at, pipeline_stage)
"""
