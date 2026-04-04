"""
Met Police data source collector.

Fetches street-level crime counts per borough from the Police Data API.
Data is typically 2 months behind — treated as static monthly enrichment.
Raw responses are saved to /data/bronze/met_police/ as timestamped JSON.
"""
