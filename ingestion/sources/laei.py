"""
LAEI modelled air quality data source.

Reads the static LAEI 2022 Population Exposure JSON produced by
scripts/fetch_laei.py and returns it in the standard fetch() format
expected by the Bronze layer.

This is a static dataset (GLA releases LAEI every 3 years at most), so
fetch() reads from disk rather than making network calls. The scheduler
runs it on the daily (slow sources) cadence alongside the other static
layers (Met Police, NHS A&E, green_space).

LAEI data is the ground-level population-weighted annual mean
concentration of NO2 and PM2.5 per borough for the LAEI 2022 baseline.
It complements — does not replace — the live OpenAQ signal, which covers
only 24/33 boroughs with station-based hourly readings.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_STATIC_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "static" / "laei_air_quality.json"


def fetch() -> dict:
    """Read LAEI air quality data from the static JSON file.

    Returns:
        Dict with 'results' (list of per-borough NO2 + PM2.5 values) and
        'fetched_at'.

    Raises:
        FileNotFoundError: If laei_air_quality.json has not been generated yet.
    """
    if not _STATIC_PATH.exists():
        raise FileNotFoundError(
            f"LAEI air quality data not found at {_STATIC_PATH}. "
            "Run: python scripts/fetch_laei.py"
        )

    with open(_STATIC_PATH, encoding="utf-8") as f:
        data = json.load(f)

    boroughs = data.get("boroughs", {})
    results = []
    for code, info in boroughs.items():
        results.append({
            "borough_code": code,
            "borough_name": info.get("name"),
            "no2": info.get("no2"),
            "pm25": info.get("pm25"),
        })

    logger.info("LAEI fetch: %d boroughs from static file", len(results))

    return {
        "results": results,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
