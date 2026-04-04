"""
Met Police data source collector.

Fetches street-level crime data from the UK Police Data API.
Data is published monthly (~2 months behind real-time) — the latest available
month is discovered dynamically from the API rather than hardcoded.

5 sample borough centroids are used as placeholders until schemas.py is built
with all 33 ONS borough centroids. Raw responses are saved to
/data/bronze/met_police/ as timestamped JSON. No transformation or
deduplication here — that happens in the silver layer.
"""

import logging
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

MET_POLICE_BASE = "https://data.police.uk/api"

# Placeholder centroids — replaced with all 33 ONS borough centroids once schemas.py is built
SAMPLE_CENTROIDS = [
    (51.5074, -0.1278),  # Westminster (central)
    (51.5155, -0.0922),  # Tower Hamlets (east)
    (51.4613, -0.1156),  # Lambeth (south)
    (51.5465, -0.1058),  # Islington (north)
    (51.4994, -0.2247),  # Hammersmith (west)
]


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
    """Fetch street-level crime data for sample London borough centroids.

    Discovers the latest available month dynamically, then queries each
    centroid. Returns all crime records combined into a single raw dict.

    Returns:
        Dict with 'results' (list of crime objects), 'date', and 'fetched_at'.

    Raises:
        RuntimeError: If the latest available month cannot be determined.
        requests.HTTPError: If any centroid API call returns a non-2xx status.
        requests.RequestException: On network or timeout errors.
    """
    date_str = _latest_available_month()
    if not date_str:
        raise RuntimeError("Met Police: could not determine latest available month")

    logger.info("Met Police: fetching data for %s", date_str)

    all_crimes: list[dict] = []

    for lat, lng in SAMPLE_CENTROIDS:
        try:
            response = requests.get(
                f"{MET_POLICE_BASE}/crimes-street/all-crime",
                params={"lat": lat, "lng": lng, "date": date_str},
                timeout=60,
            )
            response.raise_for_status()
            crimes = response.json()
            all_crimes.extend(crimes)
            logger.info("Met Police: %d crimes at (%.4f, %.4f)", len(crimes), lat, lng)
        except requests.HTTPError as e:
            logger.error("Met Police HTTP error at (%.4f, %.4f): %s", lat, lng, e)
            raise
        except requests.RequestException as e:
            logger.error("Met Police request failed at (%.4f, %.4f): %s", lat, lng, e)
            raise

    logger.info(
        "Met Police fetch: retrieved %d crimes across %d centroids",
        len(all_crimes),
        len(SAMPLE_CENTROIDS),
    )

    return {
        "results": all_crimes,
        "date": date_str,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
