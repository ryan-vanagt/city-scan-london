"""
Fetch LAEI 2022 borough-level population-weighted air quality concentrations.

Source
------
GLA's London Atmospheric Emissions Inventory (LAEI) 2022, "Population
Exposure and Road Exceedances" dataset. Ships as a 2.5MB ZIP containing
an XLSX with per-borough population-weighted annual mean concentrations
for NO2 and PM2.5 at the LAEI 2022 baseline (year 2022).

Download: https://data.london.gov.uk/download/2lg5g/f56/LAEI2022-Population-Exposure-and-Proportion-Road-Length-Exceeding-Stats.zip

Why this dataset over the broader LAEI 2022 concentrations (20m grid CSV):
  - Pre-aggregated per borough (no spatial-join work on our side)
  - Population-weighted — matches our green-space access-weighted
    methodology philosophically (measures what residents live in, not
    what the land has)
  - Single small download vs. 180MB of gridded CSV

Output
------
`data/static/laei_air_quality.json` with structure:

    {
      "_metadata": {
        "source": "LAEI 2022 Population Exposure (GLA, via TfL Strategic Analysis)",
        "url": "<download URL>",
        "baseline_year": 2022,
        "published": "December 2025 / updated August 2025",
        "units": "µg/m³",
        "method": "Population-weighted annual mean (ground-level) using OA-level concentrations",
        "fetched": "<ISO timestamp>",
        "borough_count": <int>
      },
      "boroughs": {
        "E09000001": {"name": "City of London", "no2": 30.19, "pm25": 10.82},
        ...
      }
    }

Usage
-----
    python scripts/fetch_laei.py
    python scripts/fetch_laei.py --url <custom URL>  # e.g. if LAEI 2023 lands

Safe to re-run. Overwrites the static JSON in place.
"""

import argparse
import io
import json
import logging
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import openpyxl
import requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = PROJECT_ROOT / "data" / "static" / "laei_air_quality.json"

LAEI_ZIP_URL = (
    "https://data.london.gov.uk/download/2lg5g/f56/"
    "LAEI2022-Population-Exposure-and-Proportion-Road-Length-Exceeding-Stats.zip"
)
XLSX_NAME_IN_ZIP = "5. Population Exposure/LAEI2022_AQExceedingPopulation_RoadStats.xlsx"

# GLA display names (with ampersand etc.) → our canonical ONS borough names.
# The LAEI XLSX uses display-friendly names that don't always match the
# generate_geo_mappings.py ONS form; we map the known differences and
# fall back to identity for everything else.
NAME_CANONICAL = {
    "Barking & Dagenham":      "Barking and Dagenham",
    "Hammersmith & Fulham":    "Hammersmith and Fulham",
    "Kensington & Chelsea":    "Kensington and Chelsea",
}


def _load_borough_name_to_code() -> dict[str, str]:
    """Build a lookup from canonical borough name → ONS E09000… code.

    Reads pipeline/lookups.json (populated by scripts/generate_geo_mappings.py).
    """
    lookups_path = PROJECT_ROOT / "pipeline" / "lookups.json"
    if not lookups_path.exists():
        logger.error(
            "pipeline/lookups.json not found — run scripts/generate_geo_mappings.py first"
        )
        sys.exit(1)
    with open(lookups_path, encoding="utf-8") as f:
        data = json.load(f)
    return {info["name"]: code for code, info in data.get("boroughs", {}).items()}


def _download_xlsx(url: str) -> openpyxl.Workbook:
    """Download the LAEI ZIP, extract the AQ-exposure XLSX, return a workbook."""
    logger.info("Downloading LAEI ZIP from %s", url)
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    logger.info("Downloaded %d bytes", len(resp.content))

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        names = zf.namelist()
        if XLSX_NAME_IN_ZIP not in names:
            # Try a lenient match (in case GLA reorganises the archive)
            candidates = [n for n in names if "AQExceedingPopulation" in n and n.endswith(".xlsx")]
            if not candidates:
                raise RuntimeError(
                    f"Expected {XLSX_NAME_IN_ZIP} not found in ZIP. Contents: {names}"
                )
            target = candidates[0]
            logger.warning("Expected path missing; using closest match: %s", target)
        else:
            target = XLSX_NAME_IN_ZIP
        with zf.open(target) as xf:
            return openpyxl.load_workbook(io.BytesIO(xf.read()), read_only=True, data_only=True)


def _extract_borough_values(
    wb: openpyxl.Workbook,
    sheet_name: str,
    column_name: str,
) -> dict[str, float]:
    """Walk a Population_NO2 or Population_PM2.5 sheet, extract per-borough
    LAEI 2022 baseline concentration values.

    The sheet layout (verified manually for LAEI 2022 release):
      - Borough table header row: column 1 = 'Borough',
        column 2 = 'LAEI 2019 baseline', column 3 = 'LAEI 2022 baseline'
      - Rows directly below: borough name (col 1), 2019 value (col 2),
        2022 value (col 3).
    """
    ws = wb[sheet_name]
    # Find the header row by searching for a row whose col-1 cell equals 'Borough'
    # and whose col-3 cell contains '2022'.
    header_row_idx = None
    col_2022 = None
    for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if len(row) < 4:
            continue
        # Excel label col is index 1 (the leading `None` is col A)
        if row[1] == "Borough":
            # Find the column that is the 2022 baseline value
            for j, cell in enumerate(row):
                if cell and isinstance(cell, str) and "2022 baseline" in cell:
                    col_2022 = j
                    break
            if col_2022 is None:
                # Fallback: LAEI 2022 column is typically index 3 (one past 2019 baseline)
                col_2022 = 3
            header_row_idx = i
            break
    if header_row_idx is None:
        raise RuntimeError(f"Could not find 'Borough' header row in {sheet_name}")

    logger.info(
        "%s: header row at %d, reading %s from column index %d",
        sheet_name, header_row_idx, column_name, col_2022,
    )

    result: dict[str, float] = {}
    # Iterate rows below the header
    for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if i <= header_row_idx:
            continue
        if len(row) <= col_2022:
            continue
        name = row[1]
        value = row[col_2022]
        if not isinstance(name, str) or not name.strip():
            # Empty row = end of borough table
            if result:
                break
            continue
        if not isinstance(value, (int, float)):
            continue
        # Normalise the borough name
        canonical = NAME_CANONICAL.get(name.strip(), name.strip())
        result[canonical] = float(value)

    return result


def fetch(url: str = LAEI_ZIP_URL) -> None:
    wb = _download_xlsx(url)

    no2 = _extract_borough_values(wb, "Population_NO2", "NO2 annual mean 2022")
    pm25 = _extract_borough_values(wb, "Population_PM2.5", "PM2.5 annual mean 2022")

    logger.info("Extracted NO2 for %d boroughs, PM2.5 for %d boroughs", len(no2), len(pm25))

    # Map names → ONS codes using our canonical lookup
    name_to_code = _load_borough_name_to_code()
    missing_no2 = [n for n in no2 if n not in name_to_code]
    missing_pm = [n for n in pm25 if n not in name_to_code]
    if missing_no2:
        logger.warning("NO2 borough names not in lookups.json: %s", missing_no2)
    if missing_pm:
        logger.warning("PM2.5 borough names not in lookups.json: %s", missing_pm)

    merged: dict[str, dict] = {}
    for name in set(no2) | set(pm25):
        code = name_to_code.get(name)
        if code is None:
            continue
        merged[code] = {
            "name": name,
            "no2": no2.get(name),
            "pm25": pm25.get(name),
        }

    if len(merged) < 33:
        logger.error(
            "Only matched %d boroughs — expected 33. Name mismatches? Rerun with "
            "debug logging to see which names didn't resolve.",
            len(merged),
        )
        sys.exit(2)

    # Sanity ranges
    no2_vals = [b["no2"] for b in merged.values() if b["no2"] is not None]
    pm_vals = [b["pm25"] for b in merged.values() if b["pm25"] is not None]
    logger.info(
        "NO2 range: %.1f–%.1f µg/m³  |  PM2.5 range: %.1f–%.1f µg/m³",
        min(no2_vals), max(no2_vals), min(pm_vals), max(pm_vals),
    )
    # Plausibility: 2022 London NO2 population-weighted ~18–31, PM2.5 ~8–11
    if not (10 < min(no2_vals) < max(no2_vals) < 60):
        logger.warning("NO2 range looks unusual — verify the source hasn't changed")
    if not (5 < min(pm_vals) < max(pm_vals) < 20):
        logger.warning("PM2.5 range looks unusual — verify the source hasn't changed")

    output = {
        "_metadata": {
            "source": "LAEI 2022 Population Exposure (GLA, via TfL Strategic Analysis)",
            "url": url,
            "baseline_year": 2022,
            "published": "November 2025 (LAEI 2022 release, dataset updated December 2025)",
            "units": "µg/m³",
            "method": "Population-weighted annual mean ground-level concentrations using OA-level concentrations",
            "fetched": datetime.now(timezone.utc).isoformat(),
            "borough_count": len(merged),
        },
        "boroughs": dict(sorted(merged.items())),
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    logger.info("Wrote %s (%d boroughs)", OUTPUT_PATH, len(merged))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", default=LAEI_ZIP_URL, help="LAEI ZIP URL")
    args = parser.parse_args()
    fetch(args.url)
