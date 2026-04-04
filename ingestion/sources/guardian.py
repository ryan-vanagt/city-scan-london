"""
Guardian API data source collector.

Fetches the latest London-tagged articles from the Guardian Content API.
Stores headline, trailText (for sentiment), and webUrl only — never the full body.
Raw responses are saved to /data/bronze/guardian/ as timestamped JSON.
"""
