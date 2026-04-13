"""
OpenAQ data source collector.

Fetches London air quality station data from the OpenAQ v3 API in two steps:
1. /locations — discover all stations in the Greater London bounding box
2. /locations/{id}/sensors — fetch latest PM2.5 and NO2 readings per station

Station discovery is cached for 24 hours to reduce API load. Only sensor
readings are fetched each hour.

Returns a combined response for bronze layer storage. Borough mapping and
score normalisation happen in the silver layer.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from ingestion.retry import retry_request

logger = logging.getLogger(__name__)

OPENAQ_BASE_URL = "https://api.openaq.org/v3"

# Bounding box covering Greater London (lon_min, lat_min, lon_max, lat_max)
LONDON_BBOX = "-0.51,51.28,0.33,51.69"

# Only fetch readings for these pollutants (used for air quality scoring)
TARGET_PARAMETERS = {"pm25", "no2"}

# Station cache: re-discover stations once per day instead of every hour
_STATION_CACHE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "bronze" / "openaq" / "_station_cache.json"
_STATION_CACHE_MAX_AGE_HOURS = 24


def _get_headers() -> dict[str, str]:
    """Build request headers with API key if available."""
    api_key = os.environ.get("OPENAQ_API_KEY", "")
    if not api_key:
        logger.warning("OPENAQ_API_KEY not set — requests may be rate-limited")
        return {}
    return {"X-API-Key": api_key}


def _load_station_cache() -> list[dict] | None:
    """Load cached station list if it exists and is fresh enough.

    Returns:
        Cached station list, or None if cache is missing/stale/corrupt.
    """
    if not _STATION_CACHE_PATH.exists():
        return None

    try:
        mtime = datetime.fromtimestamp(
            _STATION_CACHE_PATH.stat().st_mtime, tz=timezone.utc
        )
        age_hours = (datetime.now(timezone.utc) - mtime).total_seconds() / 3600
        if age_hours > _STATION_CACHE_MAX_AGE_HOURS:
            logger.info("OpenAQ: station cache is %.1f hours old — refreshing", age_hours)
            return None

        with open(_STATION_CACHE_PATH, encoding="utf-8") as f:
            stations = json.load(f)
        logger.info("OpenAQ: using cached station list (%d stations, %.1fh old)", len(stations), age_hours)
        return stations
    except (OSError, json.JSONDecodeError, TypeError) as e:
        logger.warning("OpenAQ: station cache unreadable: %s — refreshing", e)
        return None


def _save_station_cache(stations: list[dict]) -> None:
    """Persist station list to disk for reuse by future runs."""
    try:
        _STATION_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_STATION_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(stations, f)
        logger.info("OpenAQ: saved station cache (%d stations)", len(stations))
    except OSError as e:
        logger.warning("OpenAQ: failed to save station cache: %s", e)


def _fetch_locations(headers: dict[str, str]) -> list[dict]:
    """Return London air quality station metadata, using a daily cache.

    Checks for a cached station list first (valid for 24 hours). On cache
    miss, fetches from /locations and saves the result for future runs.

    Returns:
        List of station dicts from the API response or cache.
    """
    cached = _load_station_cache()
    if cached is not None:
        return cached

    params = {
        "bbox": LONDON_BBOX,
        "limit": 1000,
    }

    try:
        response = retry_request(
            requests.get,
            f"{OPENAQ_BASE_URL}/locations",
            headers=headers,
            params=params,
            timeout=30,
        )
        response.raise_for_status()
    except requests.HTTPError as e:
        logger.error("OpenAQ locations HTTP error: %s", e)
        raise
    except requests.RequestException as e:
        logger.error("OpenAQ locations request failed: %s", e)
        raise

    try:
        data = response.json()
    except requests.exceptions.JSONDecodeError as e:
        logger.error("OpenAQ locations: invalid JSON response: %s", e)
        raise
    stations = data.get("results", [])
    logger.info("OpenAQ: discovered %d stations (fresh from API)", len(stations))

    _save_station_cache(stations)

    return stations


def _fetch_latest_readings(
    stations: list[dict], headers: dict[str, str]
) -> dict[int, list[dict]]:
    """Fetch latest sensor readings for stations that have target parameters.

    Queries /locations/{id}/sensors for each relevant station. Skips stations
    that don't have PM2.5 or NO2 sensors.

    Args:
        stations: Station list from _fetch_locations.
        headers: Request headers (with API key).

    Returns:
        Dict mapping location_id → list of sensor readings, each containing
        parameter name, latest value, and datetime.
    """
    # Filter to stations that have at least one target parameter sensor
    relevant_stations = []
    for station in stations:
        sensor_params = {
            s.get("parameter", {}).get("name")
            for s in station.get("sensors", [])
        }
        if sensor_params & TARGET_PARAMETERS:
            relevant_stations.append(station)

    logger.info(
        "OpenAQ: %d/%d stations have PM2.5 or NO2 sensors",
        len(relevant_stations),
        len(stations),
    )

    readings: dict[int, list[dict]] = {}
    errors = 0

    for i, station in enumerate(relevant_stations):
        location_id = station.get("id")
        if location_id is None:
            continue
        if i > 0 and i % 50 == 0:
            logger.info("OpenAQ: fetched readings for %d/%d stations", i, len(relevant_stations))

        try:
            response = retry_request(
                requests.get,
                f"{OPENAQ_BASE_URL}/locations/{location_id}/sensors",
                headers=headers,
                timeout=15,
            )
            response.raise_for_status()
            try:
                sensor_data = response.json()
            except requests.exceptions.JSONDecodeError as e:
                logger.warning("OpenAQ: invalid JSON for location %d: %s", location_id, e)
                errors += 1
                continue
            sensors = sensor_data.get("results", [])

            station_readings = []
            for sensor in sensors:
                param_name = sensor.get("parameter", {}).get("name", "")
                if param_name not in TARGET_PARAMETERS:
                    continue
                sensor_id = sensor.get("id")
                if sensor_id is None:
                    continue
                latest = sensor.get("latest") or {}
                station_readings.append({
                    "sensor_id": sensor_id,
                    "parameter": param_name,
                    "value": latest.get("value"),
                    "datetime_utc": (latest.get("datetime") or {}).get("utc"),
                    "units": sensor.get("parameter", {}).get("units", ""),
                })

            readings[location_id] = station_readings

        except requests.RequestException as e:
            logger.warning("OpenAQ: failed for location %d: %s", location_id, e)
            errors += 1

        # OpenAQ free tier: 60 req/min. Sleep 1.1s ≈ 55 req/min — stays
        # safely under the limit to avoid 429s and account suspensions.
        time.sleep(1.1)

    logger.info(
        "OpenAQ: fetched readings for %d stations (%d errors)",
        len(readings),
        errors,
    )
    return readings


def fetch() -> dict:
    """Fetch London air quality stations and their latest PM2.5/NO2 readings.

    Two-step process:
    1. Discover stations via /locations (bounding box query)
    2. Fetch latest sensor readings via /locations/{id}/sensors

    Returns:
        Dict with 'stations' (location metadata) and 'readings' (latest values
        keyed by location_id). Both stored in bronze for traceability.

    Raises:
        requests.HTTPError: If the API returns a non-2xx status code.
        requests.RequestException: On network or timeout errors.
    """
    headers = _get_headers()

    stations = _fetch_locations(headers)
    readings = _fetch_latest_readings(stations, headers)

    # Build station list with coordinates and sensor metadata (no readings)
    station_list = []
    for station in stations:
        station_id = station.get("id")
        if station_id is None:
            continue
        station_list.append({
            "id": station_id,
            "name": station.get("name", ""),
            "locality": station.get("locality"),
            "coordinates": station.get("coordinates"),
            "sensors": [
                {
                    "id": s.get("id"),
                    "parameter": s.get("parameter", {}).get("name", ""),
                    "units": s.get("parameter", {}).get("units", ""),
                }
                for s in station.get("sensors", [])
            ],
        })

    # Flatten readings for bronze storage
    readings_list = []
    for location_id, sensor_readings in readings.items():
        for reading in sensor_readings:
            readings_list.append({
                "location_id": location_id,
                **reading,
            })

    logger.info(
        "OpenAQ fetch: %d stations, %d readings",
        len(station_list),
        len(readings_list),
    )

    return {
        "stations": station_list,
        "readings": readings_list,
    }
