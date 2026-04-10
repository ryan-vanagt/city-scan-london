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

    resp = None
    for attempt in range(3):
        try:
            resp = requests.get(ONS_API_URL, params=params, timeout=30)
            resp.raise_for_status()
            break
        except requests.RequestException as e:
            if attempt == 2:
                logger.error("ONS API request failed after 3 attempts: %s", e)
                raise
            logger.warning("ONS API attempt %d failed: %s — retrying", attempt + 1, e)
            time.sleep(2 ** attempt)

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


def _reverse_geocode_bulk(
    coords: list[tuple[float, float]],
    boroughs: dict[str, dict],
) -> list[str | None]:
    """Reverse-geocode coordinates to borough codes via postcodes.io.

    Uses the bulk endpoint (100 per request) for efficiency. Falls back to
    nearest-centroid if the API fails.

    Args:
        coords: List of (lat, lng) tuples.
        boroughs: Borough lookup for name→code resolution.

    Returns:
        List of ONS borough codes (or None), same order as input.
    """
    name_to_code = {info["name"].lower(): code for code, info in boroughs.items()}
    results: list[str | None] = [None] * len(coords)

    for batch_start in range(0, len(coords), 100):
        batch = coords[batch_start : batch_start + 100]
        geolocations = [
            {"latitude": lat, "longitude": lng} for lat, lng in batch
        ]
        try:
            resp = requests.post(
                POSTCODES_IO_URL,
                json={"geolocations": geolocations},
                timeout=30,
            )
            resp.raise_for_status()
            for j, item in enumerate(resp.json().get("result", [])):
                if item.get("result") and len(item["result"]) > 0:
                    district = item["result"][0].get("admin_district", "")
                    code = name_to_code.get(district.lower())
                    results[batch_start + j] = code
        except requests.RequestException as exc:
            logger.warning("postcodes.io bulk geocode failed: %s — falling back to centroids", exc)
            for j, (lat, lng) in enumerate(batch):
                results[batch_start + j] = _nearest_borough(lat, lng, boroughs)

    return results


def fetch_tfl_line_to_boroughs(
    boroughs: dict[str, dict],
) -> dict[str, list[str]]:
    """Derive tube-line-to-borough mapping from TfL station coordinates.

    Queries TfL's Line/{id}/StopPoints endpoint for each of the 11 tube lines,
    then reverse-geocodes each station via postcodes.io to determine its actual
    borough (using ONS boundary polygons, not centroid distance).

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
        resp = None
        for attempt in range(3):
            try:
                resp = requests.get(url, params=tfl_params, timeout=30)
                resp.raise_for_status()
                break
            except requests.RequestException as e:
                if attempt == 2:
                    logger.warning("TfL Line/%s/StopPoints failed after 3 attempts: %s — skipping", line_id, e)
                else:
                    time.sleep(2 ** attempt)
        if resp is None or not resp.ok:
            continue

        stations = resp.json()
        station_coords = []
        for station in stations:
            lat = station.get("lat")
            lon = station.get("lon")
            if lat is not None and lon is not None:
                station_coords.append((lat, lon))

        # Bulk reverse geocode via postcodes.io
        borough_codes = _reverse_geocode_bulk(station_coords, boroughs)
        borough_set = {code for code in borough_codes if code is not None}

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

# The 18 London NHS trust org codes from our NHS A&E ingestion source.
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
    2. Fetch HQ postcode, then enumerate site codes ({org_code}00–99)
    3. Collect unique postcodes from all active sites
    4. Bulk lookup postcodes via postcodes.io — returns admin_district directly
       (no intermediate geocoding or centroid matching needed)

    Args:
        boroughs: Borough lookup from fetch_ons_boroughs().

    Returns:
        Dict keyed by NHS org_code with a sorted list of ONS borough codes.
    """
    logger.info("Fetching NHS trust site locations...")
    name_to_code = {info["name"].lower(): code for code, info in boroughs.items()}

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

        # Enumerate site codes {org_code}00–{org_code}99
        site_count = 0
        consecutive_misses = 0
        for suffix in range(100):
            site_code = f"{org_code}{suffix:02d}"
            time.sleep(0.05)
            try:
                resp = requests.get(f"{NHS_ODS_API}/{site_code}", timeout=10)
                if resp.status_code != 200:
                    consecutive_misses += 1
                    if consecutive_misses >= 15:
                        break  # stop enumerating — no more sites
                    continue
                consecutive_misses = 0  # reset on any hit
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
                consecutive_misses += 1
                if consecutive_misses >= 10:
                    break
                continue

        logger.info("NHS ODS: %s → %d active sites with postcodes", org_code, site_count)

    logger.info("NHS: collected %d unique postcodes to geocode", len(postcodes_to_resolve))

    # Step 3: Bulk lookup postcodes via postcodes.io
    # Returns admin_district directly — no coordinate geocoding needed
    all_postcodes = list(postcodes_to_resolve.keys())
    trust_boroughs: dict[str, set[str]] = {}

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
                    district = item["result"].get("admin_district", "")
                    borough_code = name_to_code.get(district.lower())
                    if borough_code is None:
                        continue
                    for trust_code in postcodes_to_resolve[pc]:
                        trust_boroughs.setdefault(trust_code, set()).add(borough_code)
        except requests.RequestException as e:
            logger.warning("postcodes.io batch postcode lookup failed: %s", e)

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
# 4. OpenAQ station → borough pre-cache
# ---------------------------------------------------------------------------

# Bounding box covering Greater London (lon_min, lat_min, lon_max, lat_max)
OPENAQ_LONDON_BBOX = "-0.51,51.28,0.33,51.69"
OPENAQ_BASE_URL = "https://api.openaq.org/v3"


def fetch_openaq_station_boroughs(boroughs: dict[str, dict]) -> dict[str, str | None]:
    """Fetch all OpenAQ station coordinates for Greater London and map to boroughs.

    Queries the OpenAQ v3 /locations endpoint with the Greater London bounding
    box, then bulk-reverse-geocodes station coordinates via postcodes.io to
    resolve each station to an ONS borough code.

    The result is stored in lookups.json under 'openaq_station_boroughs'
    (keyed by location_id as a string) so that the silver layer can use this
    pre-resolved mapping without hitting postcodes.io on every pipeline run.

    Args:
        boroughs: Borough lookup from fetch_ons_boroughs().

    Returns:
        Dict mapping location_id (str) → ONS borough code or None.
    """
    logger.info("Fetching OpenAQ station locations for London bounding box...")

    api_key = os.environ.get("OPENAQ_API_KEY", "")
    headers = {"X-API-Key": api_key} if api_key else {}
    if not api_key:
        logger.warning("OPENAQ_API_KEY not set — OpenAQ requests may be rate-limited")

    params = {"bbox": OPENAQ_LONDON_BBOX, "limit": 1000}

    stations: list[dict] = []
    for attempt in range(3):
        try:
            resp = requests.get(
                f"{OPENAQ_BASE_URL}/locations",
                headers=headers,
                params=params,
                timeout=30,
            )
            resp.raise_for_status()
            stations = resp.json().get("results", [])
            break
        except requests.RequestException as exc:
            if attempt == 2:
                logger.error("OpenAQ /locations failed after 3 attempts: %s", exc)
                return {}
            logger.warning("OpenAQ /locations attempt %d failed: %s — retrying", attempt + 1, exc)
            time.sleep(2 ** attempt)

    if not stations:
        logger.warning("OpenAQ: no stations found in London bounding box")
        return {}

    logger.info("OpenAQ: discovered %d stations — resolving coordinates to boroughs", len(stations))

    # Collect station coordinates (skip stations without coordinates)
    station_ids: list[int] = []
    coords: list[tuple[float, float]] = []
    for station in stations:
        loc_id = station.get("id")
        coords_data = station.get("coordinates", {}) or {}
        lat = coords_data.get("latitude")
        lng = coords_data.get("longitude")
        if loc_id is not None and lat is not None and lng is not None:
            station_ids.append(loc_id)
            coords.append((float(lat), float(lng)))

    # Bulk reverse-geocode via postcodes.io
    borough_codes = _reverse_geocode_bulk(coords, boroughs)

    # Build mapping: location_id (str) → borough code or None
    station_borough_map: dict[str, str | None] = {}
    resolved = 0
    for loc_id, bc in zip(station_ids, borough_codes):
        station_borough_map[str(loc_id)] = bc
        if bc is not None:
            resolved += 1

    logger.info(
        "OpenAQ: resolved %d/%d stations to boroughs",
        resolved, len(station_ids),
    )
    return station_borough_map


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_MAX_DISTANCE_DEG = 0.06  # ~6-7 km at London latitude


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
    openaq_station_boroughs = fetch_openaq_station_boroughs(boroughs)

    lookups = {
        "_metadata": {
            "description": "Auto-generated by scripts/generate_geo_mappings.py",
            "sources": {
                "boroughs": "ONS Open Geography Portal (LAD boundaries May 2025)",
                "tfl_lines": "TfL Unified API (StopPoint/Mode/tube)",
                "nhs_trusts": "NHS ODS API + postcodes.io geocoding",
                "openaq_station_boroughs": "OpenAQ v3 /locations + postcodes.io reverse geocoding",
            },
        },
        "boroughs": boroughs,
        "tfl_line_to_boroughs": tfl_lines,
        "nhs_trust_to_boroughs": nhs_trusts,
        "openaq_station_boroughs": openaq_station_boroughs,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(lookups, f, indent=2, ensure_ascii=False)

    logger.info("Wrote lookups to %s", OUTPUT_PATH)

    # Summary
    logger.info("=" * 60)
    logger.info("Boroughs:       %d", len(boroughs))
    logger.info("Tube lines:     %d", len(tfl_lines))
    logger.info("NHS trusts:     %d", len(nhs_trusts))
    logger.info(
        "OpenAQ stations: %d (%d resolved to boroughs)",
        len(openaq_station_boroughs),
        sum(1 for v in openaq_station_boroughs.values() if v is not None),
    )
    logger.info("Output:         %s", OUTPUT_PATH)
    logger.info("=" * 60)

    # Warn about boroughs with no NHS trust coverage
    covered_boroughs = set()
    for codes in nhs_trusts.values():
        covered_boroughs.update(codes)
    uncovered = set(boroughs.keys()) - covered_boroughs
    if uncovered:
        names = [boroughs[c]["name"] for c in sorted(uncovered)]
        logger.warning("NHS trust coverage gaps (%d boroughs):", len(uncovered))
        for name in names:
            logger.warning("  - %s", name)
        logger.warning("These boroughs will use London-wide average NHS score in gold layer.")

    # Warn about boroughs with no tube coverage
    tube_boroughs = set()
    for codes in tfl_lines.values():
        tube_boroughs.update(codes)
    no_tube = set(boroughs.keys()) - tube_boroughs
    if no_tube:
        names = [boroughs[c]["name"] for c in sorted(no_tube)]
        logger.warning("No tube stations (%d boroughs):", len(no_tube))
        for name in names:
            logger.warning("  - %s", name)
        logger.warning("These boroughs will use London-wide average transit score in gold layer.")


if __name__ == "__main__":
    sys.exit(main() or 0)
