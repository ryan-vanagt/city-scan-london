"""
Green space (Skin organ) data source.

Reads the static GLA Green Cover 2024 JSON produced by
scripts/fetch_green_space.py and returns it in the standard fetch() format
expected by the Bronze layer.

This is a static dataset (updated annually at most), so fetch() reads from
disk rather than making network calls. The scheduler runs it on the daily
(slow sources) cadence alongside Met Police and NHS A&E.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_STATIC_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "static" / "green_space.json"


def fetch() -> dict:
    """Read green space data from the static JSON file.

    Returns:
        Dict with 'results' (list of borough dicts) and 'fetched_at'.

    Raises:
        FileNotFoundError: If green_space.json has not been generated yet.
    """
    if not _STATIC_PATH.exists():
        raise FileNotFoundError(
            f"Green space data not found at {_STATIC_PATH}. "
            "Run: python scripts/fetch_green_space.py"
        )

    with open(_STATIC_PATH, encoding="utf-8") as f:
        data = json.load(f)

    boroughs = data.get("boroughs", {})
    results = []
    for code, info in boroughs.items():
        results.append({
            "borough_code": code,
            "borough_name": info["name"],
            "green_pct": info["green_pct"],
        })

    logger.info("Green space fetch: %d boroughs loaded from static file", len(results))

    return {
        "results": results,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
