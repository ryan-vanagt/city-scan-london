"""
Static lookup tables and schema definitions.

Contains:
- ONS GLA borough code → borough name mapping (33 London boroughs)
- Borough centroid coordinates for Met Police API queries
- TfL tube line → borough mapping
- NHS trust → borough mapping
- Coordinate → borough mapping (nearest centroid)
- DuckDB table DDL statements for Silver, Gold, agent_logs, and bulletin_logs

All geographic data is loaded from pipeline/lookups.json, which is generated
by scripts/generate_geo_mappings.py from authoritative public APIs:
    - ONS Open Geography Portal (borough centroids)
    - TfL Unified API (tube station locations)
    - NHS ODS API + postcodes.io (trust site locations)
"""

import json
import logging
import math
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load generated lookup data
# ---------------------------------------------------------------------------

_LOOKUPS_PATH = Path(__file__).resolve().parent / "lookups.json"

if not _LOOKUPS_PATH.exists():
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
# Coordinate → borough mapping (nearest centroid, Euclidean)
# ---------------------------------------------------------------------------

# Maximum distance (degrees, ~5 km at London latitude) to accept a match.
# Stations farther than this from any centroid are outside Greater London.
_MAX_DISTANCE_DEG = 0.06


def coord_to_borough(lat: float, lng: float) -> str | None:
    """Map a coordinate to the nearest London borough using centroid distance.

    Uses simple Euclidean distance which is accurate enough at London's scale
    (negligible curvature over ~50 km).

    Args:
        lat: Latitude (WGS84).
        lng: Longitude (WGS84).

    Returns:
        ONS borough code, or None if the point is outside Greater London.
    """
    best_code: str | None = None
    best_dist = float("inf")

    for code, info in BOROUGHS.items():
        dist = math.sqrt((lat - info["lat"]) ** 2 + (lng - info["lng"]) ** 2)
        if dist < best_dist:
            best_dist = dist
            best_code = code

    if best_dist > _MAX_DISTANCE_DEG:
        return None

    return best_code


# ---------------------------------------------------------------------------
# DuckDB DDL
# ---------------------------------------------------------------------------

_DDL_SILVER_METRICS = """
CREATE TABLE IF NOT EXISTS silver_metrics (
    borough_code     VARCHAR NOT NULL,
    borough_name     VARCHAR NOT NULL,
    timestamp        TIMESTAMP NOT NULL,
    metric_name      VARCHAR NOT NULL,
    raw_value        DOUBLE,
    normalised_score DOUBLE NOT NULL,
    source           VARCHAR NOT NULL,
    ingested_at      TIMESTAMP NOT NULL,
    pipeline_stage   VARCHAR DEFAULT 'silver'
);
"""

_DDL_GOLD_SCORES = """
CREATE TABLE IF NOT EXISTS gold_scores (
    borough_code     VARCHAR NOT NULL,
    borough_name     VARCHAR NOT NULL,
    timestamp        TIMESTAMP NOT NULL,
    air_score        DOUBLE,
    transit_score    DOUBLE,
    sentiment_score  DOUBLE,
    immune_score     DOUBLE,
    composite_score  DOUBLE NOT NULL,
    ingested_at      TIMESTAMP NOT NULL,
    pipeline_stage   VARCHAR DEFAULT 'gold'
);
"""

_DDL_AGENT_LOGS = """
CREATE TABLE IF NOT EXISTS agent_logs (
    id               VARCHAR,
    timestamp        VARCHAR,
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
    id               VARCHAR,
    timestamp        VARCHAR,
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
