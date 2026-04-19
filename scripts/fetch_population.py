"""
Fetch ONS mid-year population estimates for London boroughs and wards.

Borough mode (default):
    Reads pipeline/lookups.json, enriches each borough entry with a "population"
    field from Nomis NM_31_1, writes the file back.

Ward mode (--wards):
    Reads ward codes from data/static/green_space.json, fetches ward-level
    populations from Nomis NM_2014_1 (2021-based small-area estimates),
    writes data/static/ward_populations.json.

Both modes are free (no API key) and safe to re-run.

Usage:
    python scripts/fetch_population.py            # boroughs only
    python scripts/fetch_population.py --wards    # wards only
    python scripts/fetch_population.py --all      # both
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOOKUPS_PATH = PROJECT_ROOT / "pipeline" / "lookups.json"
GREEN_SPACE_PATH = PROJECT_ROOT / "data" / "static" / "green_space.json"
WARD_POPS_PATH = PROJECT_ROOT / "data" / "static" / "ward_populations.json"

# Nomis endpoints
NOMIS_URL = "https://www.nomisweb.co.uk/api/v01/dataset/NM_31_1.data.json"  # LAD mid-year
NOMIS_WARD_URL = "https://www.nomisweb.co.uk/api/v01/dataset/NM_2014_1.data.json"  # ward (2021-based)
NOMIS_WARD_GEO_TYPE = "TYPE182"  # Wards as of May 2025
NOMIS_WARD_AGE_ALL = "200"       # All Ages code for NM_2014_1
NOMIS_WARD_GENDER_ALL = "0"      # Total

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


def fetch_ward_populations() -> dict[str, int]:
    """Fetch ward-level populations from Nomis NM_2014_1 (TYPE182 = May 2025 wards).

    The dataset covers England + Wales, so we pull all TYPE182 wards in one
    request and filter to the caller's codes downstream. All ages, both genders.

    Returns:
        Dict mapping ward ONS code (E05xxxxxxx) to population count.
    """
    logger.info("Fetching ward-level populations (Nomis NM_2014_1, TYPE182)...")

    params = {
        "geography": NOMIS_WARD_GEO_TYPE,
        "gender": NOMIS_WARD_GENDER_ALL,
        "c_age": NOMIS_WARD_AGE_ALL,
        "measures": "20100",
        "date": "latest",
        "select": "geography_code,obs_value",
    }

    for attempt in range(3):
        try:
            resp = requests.get(NOMIS_WARD_URL, params=params, timeout=120)
            resp.raise_for_status()
            break
        except requests.RequestException as e:
            if attempt == 2:
                logger.error("Nomis ward fetch failed after 3 attempts: %s", e)
                raise
            logger.warning("Nomis ward attempt %d failed: %s — retrying", attempt + 1, e)
            time.sleep(2 ** attempt)

    data = resp.json()
    observations = data.get("obs", [])
    if not observations:
        raise RuntimeError(
            f"Nomis NM_2014_1 returned 0 observations. Response keys: {list(data.keys())}"
        )

    ward_pops: dict[str, int] = {}
    for obs in observations:
        code = obs.get("geography", {}).get("geogcode", "")
        val = obs.get("obs_value", {}).get("value")
        if code and val is not None:
            ward_pops[code] = int(val)

    logger.info("Nomis: retrieved population for %d wards (E+W)", len(ward_pops))
    return ward_pops


def _run_borough_fetch() -> None:
    """Borough-level fetch path (original behaviour)."""
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

    enriched = 0
    for code, pop in populations.items():
        if code in boroughs:
            boroughs[code]["population"] = pop
            enriched += 1

    logger.info("Enriched %d/%d boroughs with population", enriched, len(boroughs))

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

    with open(LOOKUPS_PATH, "w", encoding="utf-8") as f:
        json.dump(lookups, f, indent=2, ensure_ascii=False)

    logger.info("Updated %s with population data", LOOKUPS_PATH)


def _run_ward_fetch() -> None:
    """Ward-level fetch path. Requires green_space.json to define which wards matter."""
    if not GREEN_SPACE_PATH.exists():
        logger.error(
            "green_space.json not found at %s — run scripts/fetch_green_space.py first",
            GREEN_SPACE_PATH,
        )
        sys.exit(1)

    with open(GREEN_SPACE_PATH, encoding="utf-8") as f:
        gla = json.load(f)
    wards_dict = gla.get("wards", {})
    if not wards_dict:
        logger.error("No wards found in green_space.json")
        sys.exit(1)

    gla_ward_codes = list(wards_dict.keys())
    logger.info("GLA wards to match: %d", len(gla_ward_codes))

    all_ward_pops = fetch_ward_populations()

    matched = {wc: all_ward_pops[wc] for wc in gla_ward_codes if wc in all_ward_pops}
    unmatched = [wc for wc in gla_ward_codes if wc not in all_ward_pops]
    match_rate = len(matched) / len(gla_ward_codes) if gla_ward_codes else 0.0

    logger.info(
        "Matched %d/%d GLA wards (%.1f%%). Unmatched: %d",
        len(matched), len(gla_ward_codes), 100 * match_rate, len(unmatched),
    )

    if unmatched:
        # Log borough-level coverage so gaps are visible
        from collections import Counter
        unmatched_by_borough = Counter(
            wards_dict[wc].get("borough_code", "") for wc in unmatched
        )
        logger.warning(
            "Unmatched wards by borough: %s",
            dict(unmatched_by_borough),
        )

    if match_rate < 0.90:
        logger.error(
            "Match rate %.1f%% below 90%% threshold — refusing to write output. "
            "Check Nomis geography vintage vs GLA ward codes.",
            100 * match_rate,
        )
        sys.exit(2)

    # Sanity check: ward pop sums should be close to borough totals
    if LOOKUPS_PATH.exists():
        with open(LOOKUPS_PATH, encoding="utf-8") as f:
            lookups = json.load(f)
        borough_pops = {
            code: info.get("population")
            for code, info in lookups.get("boroughs", {}).items()
            if info.get("population") is not None
        }
        from collections import defaultdict
        borough_sums: dict[str, int] = defaultdict(int)
        for wc, pop in matched.items():
            bc = wards_dict[wc].get("borough_code")
            if bc:
                borough_sums[bc] += pop
        outliers = []
        for bc, bp in borough_pops.items():
            ws = borough_sums.get(bc, 0)
            if bp and abs(ws - bp) / bp > 0.15:
                outliers.append((bc, ws, bp))
        if outliers:
            logger.warning(
                "Ward sums deviate >15%% from borough totals in %d boroughs: %s",
                len(outliers), outliers,
            )
        else:
            logger.info("Ward sums align with borough totals (all within ±15%%)")

    output = {
        "_metadata": {
            "source": "ONS Nomis NM_2014_1 (2021-based small-area population estimates)",
            "geography_type": NOMIS_WARD_GEO_TYPE,
            "geography_name": "Wards as of May 2025",
            "age": "All ages",
            "gender": "Total",
            "fetched": datetime.now(timezone.utc).isoformat(),
            "gla_wards_total": len(gla_ward_codes),
            "gla_wards_matched": len(matched),
            "match_rate": round(match_rate, 4),
        },
        "wards": matched,
    }
    with open(WARD_POPS_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    logger.info("Wrote %s (%d wards)", WARD_POPS_PATH, len(matched))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--wards", action="store_true", help="Fetch ward-level populations instead of borough")
    parser.add_argument("--all", action="store_true", help="Fetch both borough and ward populations")
    args = parser.parse_args()

    if args.all or not args.wards:
        _run_borough_fetch()
    if args.all or args.wards:
        _run_ward_fetch()


if __name__ == "__main__":
    sys.exit(main() or 0)
