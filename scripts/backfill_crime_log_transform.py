"""
Backfill historical gold immune + composite scores under the
log-transform crime methodology.

Context
-------
Commit 5c6aff8 switched `pipeline/silver.py:_transform_met_police` from
95th-percentile winsorisation to a `math.log1p` transform before
min-max normalisation. Historical gold rows were computed with the old
winsorise logic, producing a visible step in the Organ History chart on
deploy day (notably Westminster jumps from a capped 0 → ~43 overnight —
a methodology artefact, not a real change in crime rates).

**Why flat-line rather than re-normalise historical silver:** the old
winsorise logic saved `raw_value` AFTER capping at p95, so historical
silver rows for outlier boroughs (Westminster, City of London) have
identical capped rates even though their real per-capita rates differ
~9x. Re-normalising from those capped values can't recover the true
distribution for the outliers and therefore can't eliminate the jump
fully — it just moves it.

Flat-lining is correct because: (a) crime data updates monthly with
a ~2-month Met Police publication lag, (b) the chart's visible window
is 7–30 days, so within that window the real crime signal is effectively
stable anyway, and (c) every historical gold row becoming today's value
means the chart shows one coherent immune line under a single methodology.

This script:
  1. Reads each borough's LATEST silver crime + nhs_ae normalised scores
     (these reflect the new log-transform methodology as of the most
     recent pipeline run).
  2. Recomputes immune_score = mean(crime, nhs_ae) per borough.
  3. UPDATEs every historical gold_scores row's immune_score to that value.
  4. Recomputes composite_score per historical row using renormalised
     weights over present sub-scores.

Safe + idempotent. Run after any methodology change to the crime or
immune silver transforms to prevent chart discontinuities.

Usage
-----
    python scripts/backfill_crime_log_transform.py           # live cityscan.duckdb
    python scripts/backfill_crime_log_transform.py --db PATH # alternative DB
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from statistics import mean

import duckdb

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_weights() -> tuple[float, float, float, float, float]:
    """Duplicate of pipeline.gold._load_weights for standalone execution."""
    raw = os.environ.get("SCORE_WEIGHTS", "")
    default = (0.20, 0.20, 0.20, 0.20, 0.20)
    if not raw:
        return default
    try:
        parts = [float(x.strip()) for x in raw.split(",")]
        if len(parts) == 5 and all(w >= 0 for w in parts) and sum(parts) > 0:
            return (parts[0], parts[1], parts[2], parts[3], parts[4])
    except ValueError:
        pass
    return default


def _latest_immune_per_borough(con: duckdb.DuckDBPyConnection) -> dict[str, float]:
    """For each borough, compute immune = mean(latest crime, latest nhs_ae)
    using the CURRENT silver state (which reflects the new methodology).

    Returns a dict of borough_code → immune_score (may exclude boroughs
    with neither silver source available).
    """
    rows = con.execute("""
        WITH latest_crime AS (
            SELECT borough_code, normalised_score AS crime_score
            FROM (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY borough_code ORDER BY ingested_at DESC
                ) AS rn
                FROM silver_metrics
                WHERE metric_name = 'crime' AND source = 'met_police'
            )
            WHERE rn = 1
        ),
        latest_nhs AS (
            SELECT borough_code, normalised_score AS nhs_score
            FROM (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY borough_code ORDER BY ingested_at DESC
                ) AS rn
                FROM silver_metrics
                WHERE metric_name = 'nhs_ae'
            )
            WHERE rn = 1
        )
        SELECT COALESCE(lc.borough_code, ln.borough_code) AS bc,
               lc.crime_score, ln.nhs_score
        FROM latest_crime lc
        FULL OUTER JOIN latest_nhs ln ON lc.borough_code = ln.borough_code
    """).fetchall()

    result = {}
    for bc, crime, nhs in rows:
        parts = [v for v in (crime, nhs) if v is not None]
        if parts:
            result[bc] = sum(parts) / len(parts)
    return result


def backfill(db_path: Path) -> None:
    if not db_path.exists():
        logger.error("Database not found: %s", db_path)
        sys.exit(1)

    logger.info("Opening %s for backfill", db_path)
    con = duckdb.connect(str(db_path))

    try:
        latest_immune = _latest_immune_per_borough(con)
        logger.info(
            "Computed latest immune_score for %d boroughs from current silver state",
            len(latest_immune),
        )
        if not latest_immune:
            logger.warning(
                "No silver crime or nhs_ae data found — run the pipeline first. Aborting."
            )
            sys.exit(2)

        weights = _load_weights()
        w_air, w_tr, w_se, w_im, w_gs = weights

        gold_rows = con.execute("""
            SELECT borough_code, timestamp, ingested_at,
                   air_score, transit_score, sentiment_score, immune_score,
                   green_space_score, composite_score
            FROM gold_scores
            ORDER BY borough_code, ingested_at
        """).fetchall()
        logger.info("Processing %d historical gold rows…", len(gold_rows))

        updated = 0
        skipped_no_target = 0
        for (bc, ts, ing, air, transit, sentiment, old_immune,
             green_space, old_composite) in gold_rows:
            new_immune = latest_immune.get(bc)
            if new_immune is None:
                skipped_no_target += 1
                continue

            # Recompute composite: use all existing sub-scores + new immune,
            # renormalised over present values (same logic as gold.aggregate)
            pairs = [
                (air,         w_air),
                (transit,     w_tr),
                (sentiment,   w_se),
                (new_immune,  w_im),
                (green_space, w_gs),
            ]
            present = [(s, w) for s, w in pairs if s is not None]
            if not present:
                continue
            total_w = sum(w for _, w in present)
            new_composite = round(sum(s * w for s, w in present) / total_w, 2)
            new_composite = max(0.0, min(100.0, new_composite))

            # Idempotence: skip unchanged rows
            immune_same = (
                old_immune is not None
                and abs(new_immune - old_immune) < 0.01
            )
            comp_same = (
                old_composite is not None
                and abs(new_composite - old_composite) < 0.01
            )
            if immune_same and comp_same:
                continue

            con.execute("""
                UPDATE gold_scores
                SET immune_score = ?, composite_score = ?
                WHERE borough_code = ? AND timestamp = ? AND ingested_at = ?
            """, [new_immune, new_composite, bc, ts, ing])
            updated += 1

        logger.info(
            "Gold: updated %d rows, skipped %d (no silver source available)",
            updated, skipped_no_target,
        )

        # Sanity check: per-borough immune range should now be ±0.01 (flat-lined)
        sample = con.execute("""
            SELECT borough_name,
                   MIN(immune_score), MAX(immune_score), COUNT(*)
            FROM gold_scores
            WHERE borough_name IN ('Westminster', 'City of London', 'Hackney', 'Newham')
            GROUP BY borough_name ORDER BY borough_name
        """).fetchall()
        logger.info("Sanity check — immune_score range per borough across all history:")
        for name, mn, mx, n in sample:
            mn_s = f"{mn:.2f}" if mn is not None else "NULL"
            mx_s = f"{mx:.2f}" if mx is not None else "NULL"
            spread = f"{mx - mn:.2f}" if (mn is not None and mx is not None) else "—"
            logger.info("  %-18s  min=%s  max=%s  spread=%s  n=%d", name, mn_s, mx_s, spread, n)
    finally:
        con.close()

    logger.info("Done. Remember to refresh the read replica (copy to cityscan_read.duckdb).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", default=str(PROJECT_ROOT / "data" / "cityscan.duckdb"),
                        help="Path to cityscan.duckdb (write DB)")
    args = parser.parse_args()
    backfill(Path(args.db))
