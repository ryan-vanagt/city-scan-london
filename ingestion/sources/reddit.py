"""
Reddit data source collector.

Fetches the top 50 hot posts from r/london and r/londonuk using Reddit's
public JSON API — no credentials required. Only post metadata and titles
are stored; selftext (post body) is never written to disk.
Sentiment scoring of titles happens in the silver layer.
"""

import logging
import os
import time
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

SUBREDDITS = ["london"]
REDDIT_BASE = "https://www.reddit.com"


def fetch() -> dict:
    """Fetch top 50 hot text posts from r/london.

    Uses Reddit's public JSON API — no API key required.
    Filters to self/text posts only (is_self=True) — image and link posts
    are skipped as they have no text signal for sentiment scoring.
    Never stores selftext (post body).

    Returns:
        Dict with 'results' (list of post metadata dicts) and 'fetched_at'.

    Raises:
        requests.HTTPError: If Reddit returns a non-2xx status.
        requests.RequestException: On network or timeout errors.
    """
    user_agent = os.environ.get("REDDIT_USER_AGENT", "cityscan/1.0")
    headers = {"User-Agent": user_agent}

    all_posts: list[dict] = []

    for i, subreddit in enumerate(SUBREDDITS):
        if i > 0:
            time.sleep(1)  # Reddit rate limit: 1 req/sec

        url = f"{REDDIT_BASE}/r/{subreddit}/hot.json"
        try:
            response = requests.get(
                url,
                headers=headers,
                params={"limit": 50},
                timeout=30,
            )
            response.raise_for_status()
        except requests.HTTPError as e:
            logger.error("Reddit HTTP error for r/%s: %s", subreddit, e)
            raise
        except requests.RequestException as e:
            logger.error("Reddit request failed for r/%s: %s", subreddit, e)
            raise

        posts = response.json().get("data", {}).get("children", [])
        text_posts = 0
        for post in posts:
            d = post.get("data", {})
            if not d.get("is_self"):
                continue  # skip image/link posts — no text to score sentiment on
            all_posts.append({
                "id": d.get("id"),
                "subreddit": subreddit,
                "title": d.get("title"),
                "url": d.get("url"),
                "permalink": f"https://reddit.com{d.get('permalink', '')}",
                "score": d.get("score"),
                "upvote_ratio": d.get("upvote_ratio"),
                "num_comments": d.get("num_comments"),
                "created_utc": d.get("created_utc"),
                "is_self": True,
            })
            text_posts += 1

        logger.info("Reddit fetch: r/%s — %d text posts (of %d total)", subreddit, text_posts, len(posts))

    logger.info(
        "Reddit fetch: total %d posts across %d subreddits",
        len(all_posts),
        len(SUBREDDITS),
    )

    return {
        "results": all_posts,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
