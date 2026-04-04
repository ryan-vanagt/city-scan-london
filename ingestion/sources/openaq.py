"""
OpenAQ data source collector.

Fetches PM2.5, NO2, and O3 readings for London stations from the OpenAQ v3 API.
Station coordinates are mapped to ONS borough codes via bounding box lookup.
Raw responses are saved to /data/bronze/openaq/ as timestamped JSON.
"""
