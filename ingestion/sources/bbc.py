"""
BBC News London RSS data source collector.

Fetches the latest London news articles from the BBC News RSS feed.
BBC has statutory impartiality (UK Royal Charter) which balances the
Guardian's editorial left-leaning bias in the sentiment signal.

Only title and description are stored — no full article body.
Raw responses are saved to /data/bronze/bbc/ as timestamped JSON.
Sentiment scoring happens in the silver layer.
"""

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

from ingestion.retry import retry_request

logger = logging.getLogger(__name__)

BBC_RSS_URL = "https://feeds.bbci.co.uk/news/england/london/rss.xml"


def fetch() -> dict:
    """Fetch latest London news articles from the BBC News RSS feed.

    Parses the RSS XML and extracts title and description per article.
    Items with no description are skipped — they have no sentiment signal.

    Returns:
        Dict with 'results' (list of article dicts) and 'fetched_at'.

    Raises:
        requests.HTTPError: If the feed returns a non-2xx status code.
        requests.RequestException: On network or timeout errors.
    """
    try:
        response = retry_request(requests.get, BBC_RSS_URL, timeout=30)
        response.raise_for_status()
    except requests.HTTPError as e:
        logger.error("BBC RSS HTTP error: %s", e)
        raise
    except requests.RequestException as e:
        logger.error("BBC RSS request failed: %s", e)
        raise

    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as e:
        logger.error("BBC RSS: failed to parse XML response: %s", e)
        raise
    channel = root.find("channel")
    if channel is None:
        logger.error("BBC RSS: unexpected XML structure — no <channel> element")
        raise ValueError("BBC RSS feed missing <channel> element")

    articles = []
    for item in channel.findall("item"):
        title = item.findtext("title", "").strip()
        description = item.findtext("description", "").strip()
        link = item.findtext("link", "").strip()
        pub_date = item.findtext("pubDate", "").strip()

        if not description:
            continue  # skip items with no description — no sentiment signal

        articles.append({
            "title": title,
            "description": description,
            "link": link,
            "pub_date": pub_date,
        })

    logger.info("BBC fetch: retrieved %d articles", len(articles))

    return {
        "results": articles,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
