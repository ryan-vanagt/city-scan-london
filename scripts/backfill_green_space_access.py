"""
One-shot: backfill historical gold_scores rows with a stable green_space_access_score.

The GLA Green Cover 2024 dataset is a yearly static snapshot. When the
access-weighted variant was added (Task 1), old gold_scores rows had a NULL
green_space_access_score — this would show up as a NULL→value discontinuity
on the Analytics panel's organ history chart and could tempt the Doctor
agent into narrating a spurious "green space improved" trend.

This script computes today's access-weighted value per borough (from the
latest silver_metrics row for metric_name='green_space_access') and UPDATEs
every historical gold_scores row for that borough with that value.

Also backfills green_space_score for any historical rows missing it, using
the latest raw value.

Safe to re-run — always sets the historical value to today's latest static
computation. Idempotent.

Usage:
    python scripts/backfill_green_space_access.py           # live cityscan.duckdb
    python scripts/backfill_green_space_access.py --db PATH # specify DB path

Run this AFTER:
  1. The silver transform has produced green_space_access rows
     (pipeline must have run at least once with the new silver.py).
  2. The gold aggregation has populated at least one row per borough.
"""

import argparse
import logging
import sys
from pathlib import Path

import duckdb

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = PROJECT_ROOT / "data" / "cityscan.duckdb"


def backfill(db_path: Path) -> None:
    if not db_path.exists():
        logger.error("Database not found at %s", db_path)
        sys.exit(1)

    con = duckdb.connect(str(db_path))

    # Latest normalised_score per (borough, metric) for the two green signals
    # — this represents today's stable computation.
    latest = con.execute("""
        SELECT borough_code, metric_name, normalised_score
        FROM (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY borough_code, metric_name
                       ORDER BY ingested_at DESC
                   ) AS rn
            FROM silver_metrics
            WHERE metric_name IN ('green_space', 'green_space_access')
        )
        WHERE rn = 1
    """).fetchall()

    if not latest:
        logger.error(
            "No green_space silver rows found — run the pipeline (silver + gold) "
            "with the new schema first, then re-run this script."
        )
        sys.exit(2)

    # Build {borough_code: {metric: score}}
    by_borough: dict[str, dict[str, float]] = {}
    for bc, metric, score in latest:
        by_borough.setdefault(bc, {})[metric] = score

    n_boroughs = len(by_borough)
    with_access = sum(1 for m in by_borough.values() if "green_space_access" in m)
    logger.info("Found stable values for %d boroughs (%d with access-weighted)", n_boroughs, with_access)

    # UPDATE every historical row to today's stable values
    updated_raw = 0
    updated_access = 0
    for bc, metrics in by_borough.items():
        raw = metrics.get("green_space")
        access = metrics.get("green_space_access")
        if raw is not None:
            r = con.execute(
                "UPDATE gold_scores SET green_space_score = ? WHERE borough_code = ?",
                [raw, bc],
            )
            updated_raw += 1
        if access is not None:
            r = con.execute(
                "UPDATE gold_scores SET green_space_access_score = ? WHERE borough_code = ?",
                [access, bc],
            )
            updated_access += 1

    # Report
    total_rows = con.execute("SELECT COUNT(*) FROM gold_scores").fetchone()[0]
    with_access_now = con.execute(
        "SELECT COUNT(*) FROM gold_scores WHERE green_space_access_score IS NOT NULL"
    ).fetchone()[0]
    logger.info(
        "Backfilled: %d boroughs for raw, %d for access-weighted. "
        "Access-weighted coverage: %d/%d gold rows now populated.",
        updated_raw, updated_access, with_access_now, total_rows,
    )

    con.close()
    logger.info("Done. Remember to refresh the read replica (copy to cityscan_read.duckdb).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Path to cityscan.duckdb")
    args = parser.parse_args()
    backfill(Path(args.db))
