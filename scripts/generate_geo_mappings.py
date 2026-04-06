"""
Generate geographic reference data for the CityScan pipeline.

Fetches borough centroids, tube-line-to-borough mappings, and NHS-trust-to-borough
mappings from authoritative public APIs, then writes them to pipeline/lookups.json.

Data sources:
    1. ONS Open Geography Portal — London borough population-weighted centroids
    2. TfL Unified API — tube station locations (StopPoint endpoint)
    3. NHS ODS API + postcodes.io — trust hospital site locations

Run once during setup, or re-run to refresh mappings:
    python scripts/generate_geo_mappings.py

Output: pipeline/lookups.json (loaded by pipeline/schemas.py at runtime)
"""

import json
import logging
import math
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = PROJECT_ROOT / "pipeline" / "lookups.json"

load_dotenv(PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# 1. ONS borough centroids
# ---------------------------------------------------------------------------

# ONS Features API — London boroughs (Local Authority Districts in Greater London)
# Uses the LAD May 2025 boundary dataset via the ONS Open Geography Portal.
# This dataset includes LAT/LONG fields (population-weighted centroids).
ONS_API_URL = (
    "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services"
    "/LAD_MAY_2025_UK_BGC_V2/FeatureServer/0/query"
)

# All 33 London borough ONS codes
LONDON_BOROUGH_CODES = [
    f"E0900{str(i).zfill(4)}" for i in range(1, 34)
]


def fetch_ons_boroughs() -> dict[str, dict]:
    """Fetch borough names and centroids from the ONS Open Geography Portal.

    Returns:
        Dict keyed by ONS code with name, lat, lng for each borough.
    """
    logger.info("Fetching ONS borough centroids...")

    # Build a WHERE clause: LAD25CD IN ('E09000001','E09000002',...)
    code_list = ",".join(f"'{c}'" for c in LONDON_BOROUGH_CODES)
    params = {
        "where": f"LAD25CD IN ({code_list})",
        "outFields": "LAD25CD,LAD25NM,LAT,LONG",
        "returnGeometry": "false",
        "f": "json",
    }

    try:
        resp = requests.get(ONS_API_URL, params=params, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error("ONS API request failed: %s", e)
        raise

    data = resp.json()
    features = data.get("features", [])

    if not features:
        raise RuntimeError(
            f"ONS API returned 0 features. Response: {json.dumps(data)[:500]}"
        )

    boroughs: dict[str, dict] = {}
    for feat in features:
        attrs = feat["attributes"]
        code = attrs["LAD25CD"]
        boroughs[code] = {
            "name": attrs["LAD25NM"],
            "lat": round(attrs["LAT"], 4),
            "lng": round(attrs["LONG"], 4),
        }

    logger.info("ONS: retrieved %d boroughs", len(boroughs))

    missing = set(LONDON_BOROUGH_CODES) - set(boroughs.keys())
    if missing:
        logger.warning("ONS: missing boroughs: %s", missing)

    return boroughs


# ---------------------------------------------------------------------------
# 2. TfL tube line → borough mapping
# ---------------------------------------------------------------------------

TFL_LINE_STOPS_URL = "https://api.tfl.gov.uk/Line/{line_id}/StopPoints"

TUBE_LINES = [
    "bakerloo", "central", "circle", "district", "hammersmith-city",
    "jubilee", "metropolitan", "northern", "piccadilly", "victoria",
    "waterloo-city",
]


def fetch_tfl_line_to_boroughs(
    boroughs: dict[str, dict],
) -> dict[str, list[str]]:
    """Derive tube-line-to-borough mapping from TfL station coordinates.

    Queries TfL's Line/{id}/StopPoints endpoint for each of the 11 tube lines,
    then maps each station's coordinates to the nearest borough centroid.

    Args:
        boroughs: Borough lookup from fetch_ons_boroughs().

    Returns:
        Dict keyed by TfL line ID with a sorted list of ONS borough codes.
    """
    logger.info("Fetching TfL tube stations per line...")

    tfl_key = os.environ.get("TFL_APP_KEY", "")
    tfl_params = {"app_key": tfl_key} if tfl_key else {}
    if not tfl_key:
        logger.warning("TFL_APP_KEY not set — requests may be rate-limited")

    line_boroughs: dict[str, set[str]] = {}

    for line_id in TUBE_LINES:
        url = TFL_LINE_STOPS_URL.format(line_id=line_id)
        try:
            resp = requests.get(url, params=tfl_params, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error("TfL Line/%s/StopPoints failed: %s", line_id, e)
            raise

        stations = resp.json()
        borough_set: set[str] = set()

        for station in stations:
            lat = station.get("lat")
            lon = station.get("lon")
            if lat is None or lon is None:
                continue

            borough_code = _nearest_borough(lat, lon, boroughs)
            if borough_code is not None:
                borough_set.add(borough_code)

        line_boroughs[line_id] = borough_set
        logger.info(
            "TfL: %s → %d stations → %d boroughs",
            line_id, len(stations), len(borough_set),
        )
        time.sleep(0.3)  # be polite to TfL API

    result = {
        line: sorted(codes) for line, codes in sorted(line_boroughs.items())
    }
    logger.info(
        "TfL: mapped %d lines to boroughs (total mappings: %d)",
        len(result),
        sum(len(v) for v in result.values()),
    )
    return result


# ---------------------------------------------------------------------------
# 3. NHS trust → borough mapping
# ---------------------------------------------------------------------------

# The 17 London NHS trust org codes from our NHS A&E ingestion source.
# These are the trust name fragments used in nhs_ae.py to filter the CSV.
LONDON_TRUST_FRAGMENTS = [
    "BARKING",
    "BARTS",
    "CHELSEA AND WESTMINSTER",
    "CROYDON",
    "EPSOM AND ST HELIER",
    "GUY'S AND ST THOMAS",
    "HILLINGDON",
    "HOMERTON",
    "IMPERIAL COLLEGE",
    "KING'S COLLEGE",
    "KINGSTON",
    "LEWISHAM AND GREENWICH",
    "LONDON NORTH WEST",
    "NORTH MIDDLESEX",
    "ROYAL FREE",
    "ST GEORGE'S",
    "UNIVERSITY COLLEGE LONDON",
    "WHITTINGTON",
]

# NHS ODS API for trust site details
NHS_ODS_API = "https://directory.spineservices.nhs.uk/ORD/2-0-0/organisations"

# postcodes.io for geocoding UK postcodes (free, no API key needed)
POSTCODES_IO_URL = "https://api.postcodes.io/postcodes"


def fetch_nhs_trust_to_boroughs(
    boroughs: dict[str, dict],
) -> dict[str, list[str]]:
    """Derive NHS-trust-to-borough mapping from trust site postcodes.

    For each London trust:
    1. Search ODS by name fragment to discover the org_code
    2. Enumerate site codes ({org_code}00 to {org_code}99) — NHS convention
       is that child site codes start with the parent trust code
    3. Collect unique postcodes from all active sites
    4. Bulk geocode postcodes via postcodes.io
    5. Map each site coordinate to the nearest borough

    Args:
        boroughs: Borough lookup from fetch_ons_boroughs().

    Returns:
        Dict keyed by NHS org_code with a sorted list of ONS borough codes.
    """
    logger.info("Fetching NHS trust site locations...")

    # Step 1: Search for each trust by name to get org codes
    trust_codes: list[str] = []
    for fragment in LONDON_TRUST_FRAGMENTS:
        time.sleep(0.3)
        try:
            resp = requests.get(
                NHS_ODS_API,
                params={
                    "Name": fragment,
                    "Status": "Active",
                    "PrimaryRoleId": "RO197",  # NHS Trust
                    "Limit": 5,
                },
                timeout=30,
            )
            resp.raise_for_status()
            results = resp.json().get("Organisations", [])
            if results:
                trust_codes.append(results[0]["OrgId"])
                logger.info(
                    "NHS ODS: %s → %s (%s)",
                    fragment,
                    results[0]["OrgId"],
                    results[0]["Name"],
                )
            else:
                logger.warning("NHS ODS: no result for fragment '%s'", fragment)
        except requests.RequestException as e:
            logger.warning("NHS ODS search failed for '%s': %s", fragment, e)

    # Step 2: Enumerate site codes per trust ({code}00–{code}99)
    # NHS convention: child site codes are trust_code + 2-digit suffix
    postcodes_to_resolve: dict[str, list[str]] = {}  # postcode → [trust_code, ...]

    for org_code in trust_codes:
        # First get the trust HQ postcode
        time.sleep(0.2)
        try:
            resp = requests.get(f"{NHS_ODS_API}/{org_code}", timeout=30)
            resp.raise_for_status()
            org_data = resp.json().get("Organisation", {})
            main_pc = org_data.get("GeoLoc", {}).get("Location", {}).get("PostCode")
            if main_pc:
                postcodes_to_resolve.setdefault(main_pc.strip(), []).append(org_code)
        except requests.RequestException as e:
            logger.warning("NHS ODS fetch failed for %s: %s", org_code, e)

        # Then enumerate site codes
        site_count = 0
        for suffix in range(100):
            site_code = f"{org_code}{suffix:02d}"
            time.sleep(0.1)
            try:
                resp = requests.get(f"{NHS_ODS_API}/{site_code}", timeout=10)
                if resp.status_code != 200:
                    continue
                site_data = resp.json().get("Organisation", {})
                if site_data.get("Status") != "Active":
                    continue
                site_pc = (
                    site_data.get("GeoLoc", {})
                    .get("Location", {})
                    .get("PostCode", "")
                    .strip()
                )
                if site_pc:
                    postcodes_to_resolve.setdefault(site_pc, []).append(org_code)
                    site_count += 1
            except requests.RequestException:
                continue

        logger.info("NHS ODS: %s → %d active sites with postcodes", org_code, site_count)

    logger.info("NHS: collected %d unique postcodes to geocode", len(postcodes_to_resolve))

    # Step 3: Bulk geocode postcodes via postcodes.io (max 100 per request)
    all_postcodes = list(postcodes_to_resolve.keys())
    geocoded: dict[str, tuple[float, float]] = {}

    for i in range(0, len(all_postcodes), 100):
        batch = all_postcodes[i : i + 100]
        try:
            resp = requests.post(
                POSTCODES_IO_URL,
                json={"postcodes": batch},
                timeout=30,
            )
            resp.raise_for_status()
            for item in resp.json().get("result", []):
                if item.get("result"):
                    pc = item["query"]
                    geocoded[pc] = (
                        item["result"]["latitude"],
                        item["result"]["longitude"],
                    )
        except requests.RequestException as e:
            logger.warning("postcodes.io batch geocode failed: %s", e)

    logger.info("NHS: geocoded %d/%d postcodes", len(geocoded), len(all_postcodes))

    # Step 4: Map each geocoded site to nearest borough
    trust_boroughs: dict[str, set[str]] = {}
    for postcode, (lat, lng) in geocoded.items():
        borough_code = _nearest_borough(lat, lng, boroughs)
        if borough_code is None:
            continue
        for trust_code in postcodes_to_resolve[postcode]:
            trust_boroughs.setdefault(trust_code, set()).add(borough_code)

    result = {
        trust: sorted(codes) for trust, codes in sorted(trust_boroughs.items())
    }
    logger.info(
        "NHS: mapped %d trusts to boroughs (total mappings: %d)",
        len(result),
        sum(len(v) for v in result.values()),
    )
    return result


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_MAX_DISTANCE_DEG = 0.06  # ~5 km at London latitude


def _nearest_borough(
    lat: float, lng: float, boroughs: dict[str, dict]
) -> str | None:
    """Find the nearest borough centroid to a given coordinate.

    Returns None if the point is farther than _MAX_DISTANCE_DEG from any centroid
    (i.e. outside Greater London).
    """
    best_code: str | None = None
    best_dist = float("inf")

    for code, info in boroughs.items():
        dist = math.sqrt((lat - info["lat"]) ** 2 + (lng - info["lng"]) ** 2)
        if dist < best_dist:
            best_dist = dist
            best_code = code

    if best_dist > _MAX_DISTANCE_DEG:
        return None
    return best_code


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Fetch all reference data and write to pipeline/lookups.json."""
    boroughs = fetch_ons_boroughs()
    tfl_lines = fetch_tfl_line_to_boroughs(boroughs)
    nhs_trusts = fetch_nhs_trust_to_boroughs(boroughs)

    lookups = {
        "_metadata": {
            "description": "Auto-generated by scripts/generate_geo_mappings.py",
            "sources": {
                "boroughs": "ONS Open Geography Portal (LAD boundaries 2024)",
                "tfl_lines": "TfL Unified API (StopPoint/Mode/tube)",
                "nhs_trusts": "NHS ODS API + postcodes.io geocoding",
            },
        },
        "boroughs": boroughs,
        "tfl_line_to_boroughs": tfl_lines,
        "nhs_trust_to_boroughs": nhs_trusts,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(lookups, f, indent=2, ensure_ascii=False)

    logger.info("Wrote lookups to %s", OUTPUT_PATH)

    # Summary
    print(f"\n{'='*60}")
    print(f"Boroughs:       {len(boroughs)}")
    print(f"Tube lines:     {len(tfl_lines)}")
    print(f"NHS trusts:     {len(nhs_trusts)}")
    print(f"Output:         {OUTPUT_PATH}")
    print(f"{'='*60}")

    # Warn about boroughs with no NHS trust coverage
    covered_boroughs = set()
    for codes in nhs_trusts.values():
        covered_boroughs.update(codes)
    uncovered = set(boroughs.keys()) - covered_boroughs
    if uncovered:
        names = [boroughs[c]["name"] for c in sorted(uncovered)]
        print(f"\nNHS trust coverage gaps ({len(uncovered)} boroughs):")
        for name in names:
            print(f"  - {name}")
        print("These boroughs will use London-wide average NHS score in gold layer.")

    # Warn about boroughs with no tube coverage
    tube_boroughs = set()
    for codes in tfl_lines.values():
        tube_boroughs.update(codes)
    no_tube = set(boroughs.keys()) - tube_boroughs
    if no_tube:
        names = [boroughs[c]["name"] for c in sorted(no_tube)]
        print(f"\nNo tube stations ({len(no_tube)} boroughs):")
        for name in names:
            print(f"  - {name}")
        print("These boroughs will use London-wide average transit score in gold layer.")


if __name__ == "__main__":
    sys.exit(main() or 0)
