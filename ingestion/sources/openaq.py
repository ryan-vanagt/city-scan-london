"""
OpenAQ data source collector.

Fetches London air quality station data from the OpenAQ v3 API in two steps:
1. /locations — discover all stations in the Greater London bounding box
2. /locations/{id}/sensors — fetch latest PM2.5 and NO2 readings per station

Returns a combined response for bronze layer storage. Borough mapping and
score normalisation happen in the silver layer.
"""

import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

OPENAQ_BASE_URL = "https://api.openaq.org/v3"

# Bounding box covering Greater London (lon_min, lat_min, lon_max, lat_max)
LONDON_BBOX = "-0.51,51.28,0.33,51.69"

# Only fetch readings for these pollutants (used for air quality scoring)
TARGET_PARAMETERS = {"pm25", "no2"}


def _get_headers() -> dict[str, str]:
    """Build request headers with API key if available."""
    api_key = os.environ.get("OPENAQ_API_KEY", "")
    if not api_key:
        logger.warning("OPENAQ_API_KEY not set — requests may be rate-limited")
        return {}
    return {"X-API-Key": api_key}


def _fetch_locations(headers: dict[str, str]) -> list[dict]:
    """Fetch all London air quality station metadata from /locations.

    Returns:
        List of station dicts from the API response.
    """
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
        logger.error("OpenAQ locations HTTP error: %s", e)
        raise
    except requests.RequestException as e:
        logger.error("OpenAQ locations request failed: %s", e)
        raise

    data = response.json()
    stations = data.get("results", [])
    logger.info("OpenAQ: discovered %d stations", len(stations))
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
        location_id = station["id"]
        if i > 0 and i % 50 == 0:
            logger.info("OpenAQ: fetched readings for %d/%d stations", i, len(relevant_stations))

        try:
            response = requests.get(
                f"{OPENAQ_BASE_URL}/locations/{location_id}/sensors",
                headers=headers,
                timeout=15,
            )
            response.raise_for_status()
            sensors = response.json().get("results", [])

            station_readings = []
            for sensor in sensors:
                param_name = sensor.get("parameter", {}).get("name", "")
                if param_name not in TARGET_PARAMETERS:
                    continue
                latest = sensor.get("latest") or {}
                station_readings.append({
                    "sensor_id": sensor["id"],
                    "parameter": param_name,
                    "value": latest.get("value"),
                    "datetime_utc": (latest.get("datetime") or {}).get("utc"),
                    "units": sensor.get("parameter", {}).get("units", ""),
                })

            readings[location_id] = station_readings

        except requests.RequestException:
            errors += 1

        # Rate limiting: ~10 requests/second for free tier
        time.sleep(0.1)

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
        station_list.append({
            "id": station["id"],
            "name": station.get("name", ""),
            "locality": station.get("locality"),
            "coordinates": station.get("coordinates"),
            "sensors": [
                {
                    "id": s["id"],
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
