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

from ingestion.sources import openaq  # noqa: E402
from pipeline import bronze  # noqa: E402

SOURCES = {
    "openaq": openaq,
    # "tfl": tfl,
    # "guardian": guardian,
    # "reddit": reddit,
    # "met_police": met_police,
}


if __name__ == "__main__":
    for name, module in SOURCES.items():
        data = module.fetch()
        path = bronze.save(name, data)
        bronze.cleanup(name)
        print(f"Saved {name} bronze data to {path}")
