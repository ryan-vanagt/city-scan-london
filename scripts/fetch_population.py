"""
Fetch ONS mid-year population estimates for London boroughs.

Reads pipeline/lookups.json, enriches each borough entry with a "population"
field from the ONS Nomis API, and writes the file back.

Data source:
    ONS Nomis API — NM_2002_1 (mid-year population estimates)
    Free, no API key required.

Run after generate_geo_mappings.py (which creates lookups.json):
    python scripts/fetch_population.py

Safe to re-run — overwrites population values with the latest available year.
"""

import json
import logging
import sys
import time
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOOKUPS_PATH = PROJECT_ROOT / "pipeline" / "lookups.json"

# ONS Nomis API — mid-year population estimates (5-year age band dataset)
NOMIS_URL = "https://www.nomisweb.co.uk/api/v01/dataset/NM_31_1.data.json"

# All 33 London borough ONS codes
LONDON_BOROUGH_CODES = [f"E0900{str(i).zfill(4)}" for i in range(1, 34)]


def fetch_ons_population(borough_codes: list[str]) -> dict[str, int]:
    """Fetch mid-year population estimates from ONS Nomis for given borough codes.

    Args:
        borough_codes: List of ONS borough codes (e.g. ["E09000001", ...]).

    Returns:
        Dict mapping ONS code to population count.
    """
    logger.info("Fetching ONS population estimates (Nomis API)...")

    # Nomis accepts ONS geography codes directly (comma-separated).
    geo_param = ",".join(borough_codes)

    params = {
        "geography": geo_param,
        "sex": "7",           # all persons
        "age": "0",           # all ages
        "measures": "20100",  # value
        "date": "latest",
        "select": "geography_code,geography_name,obs_value,date_name",
    }

    resp = None
    for attempt in range(3):
        try:
            resp = requests.get(NOMIS_URL, params=params, timeout=30)
            resp.raise_for_status()
            break
        except requests.RequestException as e:
            if attempt == 2:
                logger.error("Nomis API failed after 3 attempts: %s", e)
                raise
            logger.warning("Nomis attempt %d failed: %s — retrying", attempt + 1, e)
            time.sleep(2 ** attempt)

    data = resp.json()
    observations = data.get("obs", [])

    if not observations:
        raise RuntimeError(
            f"Nomis API returned 0 observations. Response keys: {list(data.keys())}"
        )

    populations: dict[str, int] = {}
    for obs in observations:
        geo = obs.get("geography", {})
        ons_code = geo.get("geogcode", "")
        pop = obs.get("obs_value", {}).get("value")
        if ons_code in borough_codes and pop is not None:
            populations[ons_code] = int(pop)

    logger.info("Nomis: retrieved population for %d/%d boroughs", len(populations), len(borough_codes))
    return populations


def main() -> None:
    """Read lookups.json, enrich with population, write back."""
    if not LOOKUPS_PATH.exists():
        logger.error("lookups.json not found at %s — run generate_geo_mappings.py first", LOOKUPS_PATH)
        sys.exit(1)

    with open(LOOKUPS_PATH, encoding="utf-8") as f:
        lookups = json.load(f)

    boroughs = lookups.get("boroughs", {})
    if not boroughs:
        logger.error("No boroughs found in lookups.json")
        sys.exit(1)

    borough_codes = list(boroughs.keys())
    populations = fetch_ons_population(borough_codes)

    # Enrich borough entries
    enriched = 0
    for code, pop in populations.items():
        if code in boroughs:
            boroughs[code]["population"] = pop
            enriched += 1

    logger.info("Enriched %d/%d boroughs with population", enriched, len(boroughs))

    # Sanity checks
    missing = [c for c in boroughs if "population" not in boroughs[c]]
    if missing:
        names = [boroughs[c]["name"] for c in sorted(missing)]
        logger.warning("Population missing for %d boroughs: %s", len(missing), names)

    pops = [b["population"] for b in boroughs.values() if "population" in b]
    if pops:
        total = sum(pops)
        logger.info(
            "Population range: %d (min) – %d (max), total: %d",
            min(pops), max(pops), total,
        )
        if total < 7_000_000 or total > 12_000_000:
            logger.warning("Total London population %d looks unusual (expected ~9M)", total)

    # Write back
    with open(LOOKUPS_PATH, "w", encoding="utf-8") as f:
        json.dump(lookups, f, indent=2, ensure_ascii=False)

    logger.info("Updated %s with population data", LOOKUPS_PATH)


if __name__ == "__main__":
    sys.exit(main() or 0)
