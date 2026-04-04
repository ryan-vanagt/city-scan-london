"""
OpenAQ data source collector.

Fetches all London air quality station data from the OpenAQ v3 API.
Returns the raw API response for bronze layer storage — no transformation or
borough mapping is applied here. That happens in the silver layer.
"""

import logging
import os

import requests

logger = logging.getLogger(__name__)

OPENAQ_BASE_URL = "https://api.openaq.org/v3"

# Bounding box covering Greater London (lon_min, lat_min, lon_max, lat_max)
LONDON_BBOX = "-0.51,51.28,0.33,51.69"


def fetch() -> dict:
    """Fetch all London air quality station locations from OpenAQ v3.

    Queries the /locations endpoint using a bounding box covering Greater London.
    Returns the full raw API response with no filtering or transformation.

    Returns:
        Raw API response dict containing a 'results' array of station objects.

    Raises:
        requests.HTTPError: If the API returns a non-2xx status code.
        requests.RequestException: On network or timeout errors.
    """
    api_key = os.environ.get("OPENAQ_API_KEY", "")

    headers = {"X-API-Key": api_key} if api_key else {}
    if not api_key:
        logger.warning("OPENAQ_API_KEY not set — requests may be rate-limited")

    params = {
        "bbox": LONDON_BBOX,
        "limit": 1000,
    }

    try:
        response = requests.get(
            f"{OPENAQ_BASE_URL}/locations",
            headers=headers,
            params=params,
            timeout=30,
        )
        response.raise_for_status()
    except requests.HTTPError as e:
        logger.error("OpenAQ API HTTP error: %s", e)
        raise
    except requests.RequestException as e:
        logger.error("OpenAQ API request failed: %s", e)
        raise

    data = response.json()
    result_count = len(data.get("results", []))
    logger.info("OpenAQ fetch: retrieved %d stations", result_count)

    return data
