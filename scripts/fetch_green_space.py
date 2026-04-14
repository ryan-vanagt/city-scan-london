"""
Fetch GLA Green Cover 2024 data for London boroughs and wards.

Downloads the XLSX from the London Datastore, parses the "Borough" and "Ward"
sheets, maps ward codes (E05*) to borough codes (E09*) via findthatpostcode.uk,
and writes a static JSON file. Used by the green_space ingestion source.

Data source:
    GLA Green Cover 2024 — satellite imagery + NDVI classification.
    Free, no API key required.

Run once (data is static — updated annually at most):
    python scripts/fetch_green_space.py

Safe to re-run — overwrites data/static/green_space.json.
"""

import json
import logging
import sys
import tempfile
import time
from pathlib import Path

import openpyxl
import requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = PROJECT_ROOT / "data" / "static" / "green_space.json"

XLSX_URL = (
    "https://data.london.gov.uk/download/e56n0/"
    "2a993c9b-20c5-43c6-871b-ce5e5aa5376a/"
    "2024_%20green_cover_borough_ward_stats.xlsx"
)

DATASET_URL = "https://data.london.gov.uk/dataset/green-cover-2024-e56n0/"

# All 33 London borough ONS codes
EXPECTED_CODES = {f"E0900{str(i).zfill(4)}" for i in range(1, 34)}


def download_xlsx(url: str) -> Path:
    """Download the XLSX to a temporary file and return its path."""
    logger.info("Downloading XLSX from %s", url)
    resp = None
    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            break
        except requests.RequestException as e:
            if attempt == 2:
                logger.error("Download failed after 3 attempts: %s", e)
                raise
            logger.warning("Download attempt %d failed: %s — retrying", attempt + 1, e)
            time.sleep(2 ** attempt)

    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    tmp.write(resp.content)
    tmp.close()
    logger.info("Downloaded %.1f KB to %s", len(resp.content) / 1024, tmp.name)
    return Path(tmp.name)


def parse_borough_sheet(xlsx_path: Path) -> dict[str, dict]:
    """Parse the Borough sheet and return {borough_code: {name, green_pct}}.

    The XLSX has columns: borough, borough_code, borough_area_ha,
    borough_green_sum, percentage (as a fraction 0–1).
    """
    wb = openpyxl.load_workbook(xlsx_path, read_only=True)
    if "Borough" not in wb.sheetnames:
        raise ValueError(
            f"Expected 'Borough' sheet, found: {wb.sheetnames}"
        )

    ws = wb["Borough"]
    boroughs: dict[str, dict] = {}

    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            # Header row — validate expected columns
            expected = ("borough", "borough_code", "borough_area_ha",
                        "borough_green_sum", "percentage")
            actual = tuple(str(c).lower().strip() for c in row[:5])
            if actual != expected:
                logger.warning(
                    "Unexpected column headers: %s (expected %s)", actual, expected,
                )
            continue

        name = row[0]
        code = row[1]
        pct_fraction = row[4]

        if not code or not name:
            continue

        code = str(code).strip()
        name = str(name).strip()

        if pct_fraction is None:
            logger.warning("No percentage for %s (%s) — skipping", name, code)
            continue

        green_pct = round(float(pct_fraction) * 100, 1)
        boroughs[code] = {"name": name, "green_pct": green_pct}

    wb.close()
    return boroughs


def parse_ward_sheet(xlsx_path: Path) -> list[dict]:
    """Parse the Ward sheet and return list of ward dicts.

    Each dict: {ward_name, ward_code, green_pct, area_ha}.
    Ward codes are E05* format — borough mapping done separately.
    """
    wb = openpyxl.load_workbook(xlsx_path, read_only=True)
    if "Ward" not in wb.sheetnames:
        logger.warning("No 'Ward' sheet found — skipping ward data")
        wb.close()
        return []

    ws = wb["Ward"]
    wards: list[dict] = []

    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue  # header

        name = row[0]
        code = row[1]
        area = row[2]
        pct_fraction = row[4]

        if not code or not name or pct_fraction is None:
            continue

        wards.append({
            "name": str(name).strip(),
            "ward_code": str(code).strip(),
            "green_pct": round(float(pct_fraction) * 100, 1),
            "area_ha": round(float(area), 1) if area else 0.0,
        })

    wb.close()
    logger.info("Parsed %d wards from Ward sheet", len(wards))
    return wards


def map_wards_to_boroughs(
    wards: list[dict],
    borough_codes: set[str],
) -> dict[str, dict]:
    """Map ward codes (E05*) to borough codes (E09*) via findthatpostcode.uk.

    Returns dict keyed by ward_code with borough_code added.
    Only includes wards that map to a London borough (E09*).
    """
    logger.info("Mapping %d wards to boroughs via findthatpostcode.uk...", len(wards))

    result: dict[str, dict] = {}
    mapped = 0
    failed = 0

    for i, ward in enumerate(wards):
        wc = ward["ward_code"]
        try:
            resp = requests.get(
                f"https://findthatpostcode.uk/areas/{wc}.json",
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            parent = data.get("relationships", {}).get("parent", {}).get("data", {})
            borough_code = parent.get("id", "")

            if borough_code in borough_codes:
                result[wc] = {
                    "name": ward["name"],
                    "borough_code": borough_code,
                    "green_pct": ward["green_pct"],
                    "area_ha": ward["area_ha"],
                }
                mapped += 1
            else:
                # Ward not in a London borough (could be City of London sub-area etc.)
                failed += 1
        except Exception as e:
            logger.warning("Failed to map ward %s (%s): %s", wc, ward["name"], e)
            failed += 1

        # Rate limit: 0.1s between calls
        if i < len(wards) - 1:
            time.sleep(0.1)

        # Progress log every 100 wards
        if (i + 1) % 100 == 0:
            logger.info("Ward mapping progress: %d/%d", i + 1, len(wards))

    logger.info(
        "Ward mapping complete: %d mapped, %d failed/non-London out of %d total",
        mapped, failed, len(wards),
    )
    return result


def main() -> None:
    """Download XLSX, parse, validate, and write JSON."""
    # Try downloading; fall back to local copy if available
    xlsx_path = None
    try:
        xlsx_path = download_xlsx(XLSX_URL)
    except Exception:
        # Check for pre-downloaded copy
        local = Path("/tmp/green_cover_2024.xlsx")
        if local.exists():
            logger.info("Using local copy at %s", local)
            xlsx_path = local
        else:
            logger.error("No XLSX available — cannot proceed")
            sys.exit(1)

    boroughs = parse_borough_sheet(xlsx_path)

    # Sanity checks
    found_codes = set(boroughs.keys())
    missing = EXPECTED_CODES - found_codes
    extra = found_codes - EXPECTED_CODES

    if missing:
        logger.error("Missing %d borough(s): %s", len(missing), sorted(missing))
        sys.exit(1)
    if extra:
        logger.warning("Extra borough code(s) not in ONS set: %s", sorted(extra))

    if len(boroughs) != 33:
        logger.error("Expected 33 boroughs, got %d", len(boroughs))
        sys.exit(1)

    pcts = [b["green_pct"] for b in boroughs.values()]
    for code, b in boroughs.items():
        if not (0.0 <= b["green_pct"] <= 100.0):
            logger.error(
                "Invalid green_pct for %s (%s): %.1f",
                b["name"], code, b["green_pct"],
            )
            sys.exit(1)

    logger.info(
        "Green cover range: %.1f%% (min, %s) – %.1f%% (max, %s), mean %.1f%%",
        min(pcts),
        next(b["name"] for b in boroughs.values() if b["green_pct"] == min(pcts)),
        max(pcts),
        next(b["name"] for b in boroughs.values() if b["green_pct"] == max(pcts)),
        sum(pcts) / len(pcts),
    )

    # Parse ward data and map to boroughs
    raw_wards = parse_ward_sheet(xlsx_path)
    wards: dict[str, dict] = {}
    if raw_wards:
        wards = map_wards_to_boroughs(raw_wards, EXPECTED_CODES)

    # Write output
    output = {
        "_metadata": {
            "source": "GLA Green Cover 2024",
            "url": DATASET_URL,
            "method": "Satellite imagery + NDVI classification",
            "updated": "2024",
        },
        "boroughs": boroughs,
        "wards": wards,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # Clean up temp file (skip if using local fallback)
    if xlsx_path != Path("/tmp/green_cover_2024.xlsx"):
        xlsx_path.unlink(missing_ok=True)

    logger.info("Wrote %s (%d boroughs, %d wards)", OUTPUT_PATH, len(boroughs), len(wards))


if __name__ == "__main__":
    sys.exit(main() or 0)
