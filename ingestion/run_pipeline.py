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
from pipeline import bronze, silver  # noqa: E402
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


if __name__ == "__main__":
    # --- Bronze ---
    for name, module in SOURCES.items():
        data = module.fetch()
        path = bronze.save(name, data)
        bronze.cleanup(name)
        logger.info("Saved %s bronze data to %s", name, path)

    # --- Silver ---
    con = duckdb.connect(DB_PATH)
    init_db(con)
    rows = silver.transform(con)
    logger.info("Silver layer complete: %d rows inserted", rows)
    con.close()
