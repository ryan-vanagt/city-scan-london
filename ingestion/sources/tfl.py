"""
TfL data source collector.

Fetches live disruption data across tube, bus, DLR, and Overground lines
from the TfL Unified API. Lines are mapped to borough coverage zones.
Raw responses are saved to /data/bronze/tfl/ as timestamped JSON.
"""
