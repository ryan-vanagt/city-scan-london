"""
TfL data source collector.

Fetches live tube line statuses from the TfL Unified API.
Raw responses are saved to /data/bronze/tfl/ as timestamped JSON.
Borough mapping happens in the silver layer.
"""

import logging
import os
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

TFL_BASE_URL = "https://api.tfl.gov.uk/line/mode/tube/status"


def fetch() -> dict:
    """Fetch all tube line statuses from the TfL Unified API.

    Returns the full raw API response with no filtering or transformation.

    Returns:
        Dict with 'results' (list of line status objects) and 'fetched_at' timestamp.

    Raises:
        requests.HTTPError: If the API returns a non-2xx status code.
        requests.RequestException: On network or timeout errors.
    """
    api_key = os.environ.get("TFL_APP_KEY", "")
    params = {"app_key": api_key} if api_key else {}
    if not api_key:
        logger.warning("TFL_APP_KEY not set — requests may be rate-limited")

    try:
        response = requests.get(TFL_BASE_URL, params=params, timeout=30)
        response.raise_for_status()
    except requests.HTTPError as e:
        logger.error("TfL API HTTP error: %s", e)
        raise
    except requests.RequestException as e:
        logger.error("TfL API request failed: %s", e)
        raise

    data = response.json()
    if not isinstance(data, list):
        logger.error("TfL API: expected list, got %s", type(data).__name__)
        raise ValueError(f"TfL API returned unexpected type: {type(data).__name__}")
    logger.info("TfL fetch: retrieved %d line statuses", len(data))

    return {
        "results": data,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
