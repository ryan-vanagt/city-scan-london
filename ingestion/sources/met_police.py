"""
Met Police data source collector.

Fetches street-level crime data from the UK Police Data API.
Data is published monthly (~2 months behind real-time) — the latest available
month is discovered dynamically from the API rather than hardcoded.

Queries all 33 ONS borough centroids from pipeline/schemas.py. Each crime
record is tagged with the requesting borough_code so the silver layer can
attribute crimes to boroughs without re-running coord_to_borough(). Raw
responses are saved to /data/bronze/met_police/ as timestamped JSON.
"""

import logging
import time
from datetime import datetime, timezone

import requests

from pipeline.schemas import BOROUGHS

logger = logging.getLogger(__name__)

MET_POLICE_BASE = "https://data.police.uk/api"


def _latest_available_month() -> str | None:
    """Discover the most recent month for which Met Police data is available.

    Returns:
        Month string in 'YYYY-MM' format, or None on failure.
    """
    try:
        response = requests.get(
            f"{MET_POLICE_BASE}/crimes-street-dates",
            timeout=30,
        )
        response.raise_for_status()
        months = response.json()
        # API returns list sorted newest-first; each item is {"date": "YYYY-MM", ...}
        return months[0]["date"] if months else None
    except Exception as exc:
        logger.error("Met Police: failed to fetch available dates: %s", exc)
        return None


def fetch() -> dict:
    """Fetch street-level crime data for all 33 London borough centroids.

    Discovers the latest available month dynamically, then queries each
    borough centroid. Individual centroid failures are logged and skipped
    so that partial data is still returned.

    Returns:
        Dict with 'results' (list of crime objects, each tagged with
        'borough_code'), 'date', and 'fetched_at'.

    Raises:
        RuntimeError: If the latest available month cannot be determined.
    """
    date_str = _latest_available_month()
    if not date_str:
        raise RuntimeError("Met Police: could not determine latest available month")

    logger.info("Met Police: fetching data for %s across %d boroughs", date_str, len(BOROUGHS))

    all_crimes: list[dict] = []
    failed_boroughs: list[str] = []

    for i, (borough_code, info) in enumerate(BOROUGHS.items()):
        if i > 0:
            time.sleep(1)  # Met Police API rate limit
        lat, lng = info["lat"], info["lng"]
        try:
            response = requests.get(
                f"{MET_POLICE_BASE}/crimes-street/all-crime",
                params={"lat": lat, "lng": lng, "date": date_str},
                timeout=60,
            )
            response.raise_for_status()
            crimes = response.json()
            # Tag each crime with the requesting borough code
            for crime in crimes:
                crime["borough_code"] = borough_code
            all_crimes.extend(crimes)
            logger.info(
                "Met Police: %d crimes for %s (%s)",
                len(crimes), borough_code, info["name"],
            )
        except requests.RequestException as e:
            logger.warning(
                "Met Police: failed for %s (%s): %s — skipping",
                borough_code, info["name"], e,
            )
            failed_boroughs.append(borough_code)

    if failed_boroughs:
        logger.warning(
            "Met Police: %d/%d boroughs failed: %s",
            len(failed_boroughs), len(BOROUGHS), failed_boroughs,
        )

    if not all_crimes:
        logger.error("Met Police: no crime data retrieved from any borough")

    logger.info(
        "Met Police fetch: retrieved %d crimes across %d/%d boroughs",
        len(all_crimes),
        len(BOROUGHS) - len(failed_boroughs),
        len(BOROUGHS),
    )

    return {
        "results": all_crimes,
        "date": date_str,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
