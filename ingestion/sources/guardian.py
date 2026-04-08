"""
Guardian API data source collector.

Fetches the latest London-tagged articles from the Guardian Content API.
Stores headline and trailText (for sentiment scoring in silver) only —
never the full article body. Raw responses are saved to
/data/bronze/guardian/ as timestamped JSON.
"""

import json
import logging
import os
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

GUARDIAN_BASE_URL = "https://content.guardianapis.com/search"


def fetch() -> dict:
    """Fetch the 20 most recent London articles from the Guardian Content API.

    Returns the full raw API response with no filtering or transformation.
    Only headline and trailText fields are requested — body is never fetched.

    Returns:
        Dict with 'results' (list of article dicts) and 'fetched_at'.

    Raises:
        requests.HTTPError: If the API returns a non-2xx status code.
        requests.RequestException: On network or timeout errors.
    """
    api_key = os.environ.get("GUARDIAN_API_KEY", "")
    if not api_key:
        logger.warning("GUARDIAN_API_KEY not set — requests will use test tier (limited)")

    params = {
        "q": "london",
        "tag": "uk/london",
        "show-fields": "headline,trailText",
        "page-size": 20,
        "order-by": "newest",
        "api-key": api_key or "test",
    }

    try:
        response = requests.get(GUARDIAN_BASE_URL, params=params, timeout=30)
        response.raise_for_status()
    except requests.HTTPError as e:
        logger.error("Guardian API HTTP error: %s", e)
        raise
    except requests.RequestException as e:
        logger.error("Guardian API request failed: %s", e)
        raise

    try:
        data = response.json()
    except json.JSONDecodeError as e:
        logger.error("Guardian API: invalid JSON response: %s", e)
        raise
    articles = data.get("response", {}).get("results", [])
    logger.info("Guardian fetch: retrieved %d articles", len(articles))

    return {
        "results": articles,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
