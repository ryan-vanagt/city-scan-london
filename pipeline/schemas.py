"""
Static lookup tables and schema definitions.

Contains:
- ONS GLA borough code → borough name mapping (33 London boroughs)
- Borough centroid coordinates for Met Police API queries
- TfL tube line → borough mapping
- NHS trust → borough mapping
- Coordinate → borough mapping (postcodes.io reverse geocoding)
- DuckDB table DDL statements for Silver, Gold, agent_logs, and bulletin_logs

All geographic data is loaded from pipeline/lookups.json, which is generated
by scripts/generate_geo_mappings.py from authoritative public APIs:
    - ONS Open Geography Portal (borough centroids)
    - TfL Unified API (tube station locations)
    - NHS ODS API + postcodes.io (trust site locations)
"""

import json
import logging
from pathlib import Path

import duckdb
import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load generated lookup data
# ---------------------------------------------------------------------------

_LOOKUPS_PATH = Path(__file__).resolve().parent / "lookups.json"

if not _LOOKUPS_PATH.exists():
    logger.error("Lookups file not found: %s", _LOOKUPS_PATH)
    raise FileNotFoundError(
        f"{_LOOKUPS_PATH} not found. Run: python scripts/generate_geo_mappings.py"
    )

with open(_LOOKUPS_PATH, encoding="utf-8") as _f:
    _LOOKUPS = json.load(_f)

# ---------------------------------------------------------------------------
# 33 London boroughs: ONS code → name + population-weighted centroid
# Source: ONS Open Geography Portal (LAD May 2025 boundaries)
# ---------------------------------------------------------------------------

BOROUGHS: dict[str, dict] = _LOOKUPS["boroughs"]

# Reverse lookup: borough name (lowercase) → ONS code
BOROUGH_NAME_TO_CODE: dict[str, str] = {
    info["name"].lower(): code for code, info in BOROUGHS.items()
}

# ---------------------------------------------------------------------------
# TfL tube line → boroughs served
# Source: TfL Unified API (Line/{id}/StopPoints, station coords → borough)
# ---------------------------------------------------------------------------

LINE_TO_BOROUGHS: dict[str, list[str]] = _LOOKUPS["tfl_line_to_boroughs"]

# ---------------------------------------------------------------------------
# NHS trust org_code → boroughs served
# Source: NHS ODS API (site postcodes) + postcodes.io (geocoding)
# ---------------------------------------------------------------------------

TRUST_TO_BOROUGHS: dict[str, list[str]] = _LOOKUPS["nhs_trust_to_boroughs"]

# ---------------------------------------------------------------------------
# Coordinate → borough mapping (postcodes.io reverse geocoding + cache)
# ---------------------------------------------------------------------------

# In-memory cache: (rounded lat, lng) → borough code or None
_COORD_CACHE: dict[tuple[float, float], str | None] = {}

# Round coordinates to 4 decimal places (~11m precision) for cache keys
_COORD_PRECISION = 4


def coord_to_borough(lat: float, lng: float) -> str | None:
    """Map a coordinate to a London borough using postcodes.io reverse geocoding.

    Uses the postcodes.io API which resolves against actual ONS boundary
    polygons, giving accurate results even near borough borders. Results
    are cached in memory to avoid repeated API calls for nearby coordinates.

    Falls back to None if the coordinate is outside London or if the API
    is unavailable.

    Args:
        lat: Latitude (WGS84).
        lng: Longitude (WGS84).

    Returns:
        ONS borough code, or None if the point is outside Greater London.
    """
    cache_key = (round(lat, _COORD_PRECISION), round(lng, _COORD_PRECISION))
    if cache_key in _COORD_CACHE:
        return _COORD_CACHE[cache_key]

    try:
        resp = requests.get(
            "https://api.postcodes.io/postcodes",
            params={"lon": lng, "lat": lat, "limit": 1, "radius": 2000},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get("result")
        if results and len(results) > 0:
            district = results[0].get("admin_district", "")
            code = BOROUGH_NAME_TO_CODE.get(district.lower())
            _COORD_CACHE[cache_key] = code
            return code
    except requests.RequestException as exc:
        logger.warning("postcodes.io lookup failed for (%.4f, %.4f): %s", lat, lng, exc)

    _COORD_CACHE[cache_key] = None
    return None


def coord_to_borough_bulk(
    coords: list[tuple[float, float]],
) -> list[str | None]:
    """Map multiple coordinates to London boroughs in bulk.

    Uses postcodes.io bulk reverse geocoding (up to 100 per request) for
    efficiency. Results are cached.

    Args:
        coords: List of (lat, lng) tuples.

    Returns:
        List of ONS borough codes (or None), same order as input.
    """
    results: list[str | None] = [None] * len(coords)
    to_fetch: list[tuple[int, float, float]] = []  # (index, lat, lng)

    # Check cache first
    for i, (lat, lng) in enumerate(coords):
        cache_key = (round(lat, _COORD_PRECISION), round(lng, _COORD_PRECISION))
        if cache_key in _COORD_CACHE:
            results[i] = _COORD_CACHE[cache_key]
        else:
            to_fetch.append((i, lat, lng))

    # Bulk fetch uncached coordinates (100 per request)
    for batch_start in range(0, len(to_fetch), 100):
        batch = to_fetch[batch_start : batch_start + 100]
        geolocations = [
            {"latitude": lat, "longitude": lng} for _, lat, lng in batch
        ]
        try:
            resp = requests.post(
                "https://api.postcodes.io/postcodes",
                json={"geolocations": geolocations},
                timeout=30,
            )
            resp.raise_for_status()
            api_results = resp.json().get("result", [])
            for j, item in enumerate(api_results):
                idx, lat, lng = batch[j]
                cache_key = (round(lat, _COORD_PRECISION), round(lng, _COORD_PRECISION))
                if item.get("result") and len(item["result"]) > 0:
                    district = item["result"][0].get("admin_district", "")
                    code = BOROUGH_NAME_TO_CODE.get(district.lower())
                    _COORD_CACHE[cache_key] = code
                    results[idx] = code
                else:
                    _COORD_CACHE[cache_key] = None
        except requests.RequestException as exc:
            logger.warning("postcodes.io bulk lookup failed: %s", exc)

    return results


# ---------------------------------------------------------------------------
# DuckDB DDL
# ---------------------------------------------------------------------------

_DDL_SILVER_METRICS = """
CREATE TABLE IF NOT EXISTS silver_metrics (
    borough_code     VARCHAR NOT NULL,
    borough_name     VARCHAR NOT NULL,
    timestamp        TIMESTAMPTZ NOT NULL,
    metric_name      VARCHAR NOT NULL,
    raw_value        DOUBLE,
    normalised_score DOUBLE NOT NULL CHECK (normalised_score >= 0 AND normalised_score <= 100),
    source           VARCHAR NOT NULL,
    ingested_at      TIMESTAMPTZ NOT NULL,
    pipeline_stage   VARCHAR DEFAULT 'silver'
);
"""

_DDL_GOLD_SCORES = """
CREATE TABLE IF NOT EXISTS gold_scores (
    borough_code     VARCHAR NOT NULL,
    borough_name     VARCHAR NOT NULL,
    timestamp        TIMESTAMPTZ NOT NULL,
    air_score        DOUBLE CHECK (air_score >= 0 AND air_score <= 100),
    transit_score    DOUBLE CHECK (transit_score >= 0 AND transit_score <= 100),
    sentiment_score  DOUBLE CHECK (sentiment_score >= 0 AND sentiment_score <= 100),
    immune_score     DOUBLE CHECK (immune_score >= 0 AND immune_score <= 100),
    composite_score  DOUBLE NOT NULL CHECK (composite_score >= 0 AND composite_score <= 100),
    ingested_at      TIMESTAMPTZ NOT NULL,
    pipeline_stage   VARCHAR DEFAULT 'gold'
);
"""

_DDL_AGENT_LOGS = """
CREATE TABLE IF NOT EXISTS agent_logs (
    id               VARCHAR NOT NULL,
    timestamp        VARCHAR NOT NULL,
    query            VARCHAR,
    tools_called     VARCHAR,
    tool_inputs      VARCHAR,
    tool_outputs     VARCHAR,
    sources_cited    VARCHAR,
    final_response   VARCHAR,
    latency_ms       INTEGER,
    model_used       VARCHAR
);
"""

_DDL_BULLETIN_LOGS = """
CREATE TABLE IF NOT EXISTS bulletin_logs (
    id               VARCHAR NOT NULL,
    timestamp        VARCHAR NOT NULL,
    trigger          VARCHAR,
    scores_used      VARCHAR,
    headlines_used   VARCHAR,
    output_path      VARCHAR,
    latency_ms       INTEGER
);
"""


def init_db(con: duckdb.DuckDBPyConnection) -> None:
    """Create all DuckDB tables if they do not already exist.

    Args:
        con: An open DuckDB connection.
    """
    for ddl in (_DDL_SILVER_METRICS, _DDL_GOLD_SCORES, _DDL_AGENT_LOGS, _DDL_BULLETIN_LOGS):
        con.execute(ddl)
    logger.info("DuckDB tables initialised")
