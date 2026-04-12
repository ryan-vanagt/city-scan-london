"""Ad-hoc DuckDB queries against silver_metrics. Run to explore the DB."""

import sys
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, PROJECT_ROOT)

import duckdb

DB_PATH = str(Path(PROJECT_ROOT) / "data" / "cityscan.duckdb")
con = duckdb.connect(DB_PATH, read_only=True)

print("=" * 70)
print("Silver Layer Explorer")
print("=" * 70)

# --- Overview by source ---
print("\n--- Overview by source/metric ---\n")
print(f"{'Source':12s} {'Metric':12s} {'Rows':>5s} {'Avg':>7s} {'Min':>7s} {'Max':>7s}")
print("-" * 58)
for r in con.execute("""
    SELECT source, metric_name, COUNT(*) n,
           ROUND(AVG(normalised_score), 1),
           ROUND(MIN(normalised_score), 1),
           ROUND(MAX(normalised_score), 1)
    FROM silver_metrics
    GROUP BY source, metric_name
    ORDER BY source
""").fetchall():
    print(f"{r[0]:12s} {r[1]:12s} {r[2]:5d} {r[3]:7.1f} {r[4]:7.1f} {r[5]:7.1f}")

# --- Top 5 healthiest ---
print("\n--- Top 5 Healthiest Boroughs (avg across all metrics) ---\n")
for r in con.execute("""
    SELECT borough_name, ROUND(AVG(normalised_score), 1) avg_score, COUNT(*) metrics
    FROM silver_metrics
    GROUP BY borough_name
    ORDER BY avg_score DESC
    LIMIT 5
""").fetchall():
    print(f"  {r[0]:30s} avg={r[1]:5.1f}  ({r[2]} metrics)")

# --- Bottom 5 ---
print("\n--- Bottom 5 (least healthy) ---\n")
for r in con.execute("""
    SELECT borough_name, ROUND(AVG(normalised_score), 1) avg_score, COUNT(*) metrics
    FROM silver_metrics
    GROUP BY borough_name
    ORDER BY avg_score ASC
    LIMIT 5
""").fetchall():
    print(f"  {r[0]:30s} avg={r[1]:5.1f}  ({r[2]} metrics)")

# --- Score distribution ---
print("\n--- Score distribution (all sources) ---\n")
for r in con.execute("""
    SELECT
        CASE
            WHEN normalised_score >= 80 THEN 'green  (80-100)'
            WHEN normalised_score >= 50 THEN 'amber  (50-79)'
            ELSE                             'red    (0-49)'
        END AS band,
        COUNT(*) n,
        ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) pct
    FROM silver_metrics
    GROUP BY band
    ORDER BY band
""").fetchall():
    print(f"  {r[0]:20s} {r[1]:4d} rows  ({r[2]}%)")

# --- Total stats ---
total = con.execute("SELECT COUNT(*), COUNT(DISTINCT borough_code), COUNT(DISTINCT source) FROM silver_metrics").fetchone()
print(f"\nTotal: {total[0]} rows, {total[1]} boroughs, {total[2]} sources")

ts = con.execute("SELECT MAX(ingested_at) FROM silver_metrics").fetchone()[0]
print(f"Latest ingestion: {ts}")

con.close()
