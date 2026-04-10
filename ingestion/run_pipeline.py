"""
One-shot manual pipeline trigger for development use.

Runs a single full cycle: fetch all sources → Bronze → Silver → Gold → embed.
Not used in production (scheduler.py handles that).
"""

import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

# Resolve project root so this script can be run from any working directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

import duckdb  # noqa: E402

from ingestion.sources import openaq, tfl, met_police, guardian, reddit, bbc, nhs_ae  # noqa: E402
from pipeline import bronze, gold, silver  # noqa: E402
from pipeline.embed import embed_gold_scores  # noqa: E402
from pipeline.schemas import init_db  # noqa: E402

logger = logging.getLogger(__name__)

SOURCES = {
    "openaq": openaq,
    "tfl": tfl,
    "guardian": guardian,
    "bbc": bbc,
    "reddit": reddit,
    "met_police": met_police,
    "nhs_ae": nhs_ae,
}

DB_PATH = str(PROJECT_ROOT / "data" / "cityscan.duckdb")


def run() -> None:
    """Execute a single full pipeline cycle: Bronze → Silver → Gold → Embed.

    Bronze fetch failures are logged and skipped so partial runs can still
    produce Silver/Gold output. The DuckDB connection is always closed via
    finally, even if Silver, Gold, or Embed stages raise.
    """
    # --- Bronze ---
    for name, module in SOURCES.items():
        try:
            data = module.fetch()
            path = bronze.save(name, data)
            bronze.cleanup(name)
            logger.info("Saved %s bronze data to %s", name, path)
        except Exception as exc:
            logger.error("Bronze fetch failed for %s: %s — skipping", name, exc)
            continue

    # --- Silver / Gold / Embed ---
    con = duckdb.connect(DB_PATH)
    try:
        init_db(con)

        # Silver
        rows = silver.transform_all()
        inserted = silver.load(con, rows)
        logger.info("Silver layer complete: %d rows transformed, %d inserted", len(rows), inserted)

        # Gold
        gold_rows = gold.aggregate(con)
        logger.info("Gold layer complete: %d rows inserted", gold_rows)

        # Embed
        embedded = embed_gold_scores(con)
        logger.info("Embed layer complete: %d documents upserted", embedded)

    except Exception as exc:
        logger.error("Pipeline failed in Silver/Gold/Embed stage: %s", exc)
        raise
    finally:
        con.close()


if __name__ == "__main__":
    run()
