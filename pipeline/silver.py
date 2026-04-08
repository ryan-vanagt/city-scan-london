"""
Silver layer transformer.

Reads Bronze JSON files, parses and validates each source, maps to ONS borough codes,
normalises raw values to 0–100 scores, and returns rows for the DuckDB silver_metrics table.
Schema: (borough_code, borough_name, timestamp, metric_name, raw_value,
         normalised_score, source, ingested_at, pipeline_stage)

Transform and load are separated: transform_all() produces rows, load() inserts them.
"""

import json
import logging
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean

import duckdb

from pipeline.schemas import (
    BOROUGHS,
    LINE_TO_BOROUGHS,
    TRUST_TO_BOROUGHS,
    coord_to_borough,
    coord_to_borough_bulk,
)
from sentiment.scorer import score_texts

logger = logging.getLogger(__name__)

BRONZE_BASE = Path(__file__).resolve().parent.parent / "data" / "bronze"

# Readings older than this are considered stale and filtered out
_MAX_READING_AGE_DAYS = 7


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clamp(score: float) -> float:
    """Clamp a score to [0, 100]."""
    return max(0.0, min(100.0, score))


def _latest_bronze_file(source: str) -> Path | None:
    """Return the most recent bronze JSON file for a source, or None."""
    source_dir = BRONZE_BASE / source
    if not source_dir.exists():
        return None
    files = sorted(source_dir.glob("*.json"))
    return files[-1] if files else None


def _load_bronze(source: str) -> tuple[dict | list, str] | None:
    """Load the latest bronze file for a source.

    Returns:
        Tuple of (data, timestamp_iso) or None if no file found.
    """
    path = _latest_bronze_file(source)
    if path is None:
        logger.warning("Silver: no bronze file for source '%s'", source)
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    # Use fetched_at from data if available, otherwise derive from filename
    timestamp = None
    if isinstance(data, dict):
        timestamp = data.get("fetched_at")
    if not timestamp:
        # Filename format: YYYYMMDD_HHMMSS.json
        stem = path.stem  # e.g. "20260408_120000"
        try:
            dt = datetime.strptime(stem, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
            timestamp = dt.isoformat()
        except ValueError:
            timestamp = datetime.now(timezone.utc).isoformat()
    return data, timestamp


def _make_row(
    borough_code: str,
    timestamp: str,
    metric_name: str,
    raw_value: float | None,
    normalised_score: float,
    source: str,
) -> tuple:
    """Build a silver_metrics row tuple."""
    return (
        borough_code,
        BOROUGHS[borough_code]["name"],
        timestamp,
        metric_name,
        raw_value,
        _clamp(normalised_score),
        source,
        datetime.now(timezone.utc).isoformat(),
        "silver",
    )


# ---------------------------------------------------------------------------
# Source transformers
# ---------------------------------------------------------------------------


def _transform_nhs_ae(data: dict, timestamp: str) -> list[tuple]:
    """Transform NHS A&E bronze data to silver rows.

    metric_name: 'nhs_ae'
    normalised_score: pct_within_4hrs calculated from raw counts (higher = healthier)
    """
    results = data.get("results", [])
    if not results:
        logger.warning("Silver NHS A&E: no results in bronze data")
        return []

    # Accumulate per-borough via trust→borough mapping
    borough_pcts: dict[str, list[float]] = defaultdict(list)

    for trust in results:
        org_code = trust.get("org_code", "")
        total = trust.get("total_type1_attendances")
        over_4hrs = trust.get("over_4hrs_type1")

        # Support both old format (with pct_within_4hrs) and new format (raw counts)
        pct = trust.get("pct_within_4hrs")
        if pct is None and total and total > 0:
            pct = round((total - (over_4hrs or 0)) / total * 100, 1)

        if pct is None:
            continue

        borough_codes = TRUST_TO_BOROUGHS.get(org_code, [])
        if not borough_codes:
            logger.debug("Silver NHS A&E: trust %s not in borough mapping", org_code)
            continue
        for bc in borough_codes:
            borough_pcts[bc].append(pct)

    rows = []
    for bc, pcts in borough_pcts.items():
        avg_pct = mean(pcts)
        rows.append(_make_row(bc, timestamp, "nhs_ae", avg_pct, _clamp(avg_pct), "nhs_ae"))

    logger.info("Silver NHS A&E: %d borough rows", len(rows))
    return rows


def _transform_tfl(data: dict, timestamp: str) -> list[tuple]:
    """Transform TfL tube status bronze data to silver rows.

    metric_name: 'transit'
    normalised_score: min(severity) * 10 across lines serving the borough
    """
    results = data.get("results", [])
    if not results:
        logger.warning("Silver TfL: no results in bronze data")
        return []

    # Get severity per line
    line_severity: dict[str, int] = {}
    for line in results:
        line_id = line.get("id", "").lower()
        statuses = line.get("lineStatuses", [])
        if statuses:
            severity = statuses[0].get("statusSeverity", 0)
            line_severity[line_id] = severity

    # Map to boroughs: each borough gets the min severity across its lines
    borough_severities: dict[str, list[int]] = defaultdict(list)
    for line_id, severity in line_severity.items():
        borough_codes = LINE_TO_BOROUGHS.get(line_id, [])
        for bc in borough_codes:
            borough_severities[bc].append(severity)

    rows = []
    for bc, severities in borough_severities.items():
        min_sev = min(severities)
        raw_value = float(min_sev)
        normalised = _clamp(min_sev * 10.0)
        rows.append(_make_row(bc, timestamp, "transit", raw_value, normalised, "tfl"))

    logger.info("Silver TfL: %d borough rows", len(rows))
    return rows


def _transform_met_police(data: dict, timestamp: str) -> list[tuple]:
    """Transform Met Police crime bronze data to silver rows.

    metric_name: 'crime'
    normalised_score: min-max inverted (fewer crimes = higher score)
    """
    results = data.get("results", [])
    if not results:
        logger.warning("Silver Met Police: no results in bronze data")
        return []

    # Count crimes per borough (using tagged borough_code from fetcher)
    borough_counts: dict[str, int] = defaultdict(int)
    for crime in results:
        bc = crime.get("borough_code")
        if bc and bc in BOROUGHS:
            borough_counts[bc] += 1

    if not borough_counts:
        logger.warning("Silver Met Police: no crimes mapped to boroughs")
        return []

    # Min-max normalise, inverted: fewer crimes = higher score
    counts = list(borough_counts.values())
    min_count = min(counts)
    max_count = max(counts)
    range_count = max_count - min_count if max_count != min_count else 1

    rows = []
    for bc, count in borough_counts.items():
        raw_value = float(count)
        normalised = _clamp(100.0 * (1.0 - (count - min_count) / range_count))
        rows.append(_make_row(bc, timestamp, "crime", raw_value, normalised, "met_police"))

    logger.info("Silver Met Police: %d borough rows", len(rows))
    return rows


def _transform_openaq(data: dict, timestamp: str) -> list[tuple]:
    """Transform OpenAQ air quality bronze data to silver rows.

    metric_name: 'air_quality'
    normalised_score: exponential decay from WHO guideline ratios

    Filters out stale readings (older than _MAX_READING_AGE_DAYS).
    Only scores boroughs that have at least one reading for each available
    parameter, weighting the formula by what's present.
    """
    stations = data.get("stations", [])
    readings = data.get("readings", [])

    if not readings:
        logger.warning("Silver OpenAQ: no readings in bronze data")
        return []

    # Filter stale readings
    cutoff = datetime.now(timezone.utc) - timedelta(days=_MAX_READING_AGE_DAYS)
    fresh_readings = []
    stale_count = 0
    for reading in readings:
        dt_str = reading.get("datetime_utc")
        if dt_str:
            try:
                dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                if dt < cutoff:
                    stale_count += 1
                    continue
            except (ValueError, TypeError):
                pass  # keep readings with unparseable dates
        fresh_readings.append(reading)

    if stale_count:
        logger.info(
            "Silver OpenAQ: filtered %d stale readings (>%d days old), %d fresh remain",
            stale_count, _MAX_READING_AGE_DAYS, len(fresh_readings),
        )

    if not fresh_readings:
        logger.warning("Silver OpenAQ: no fresh readings after filtering")
        return []

    # Build station coordinate lookup
    station_coords: dict[int, tuple[float, float]] = {}
    for station in stations:
        coords = station.get("coordinates")
        if coords and coords.get("latitude") is not None:
            station_coords[station["id"]] = (
                coords["latitude"],
                coords["longitude"],
            )

    # Bulk-resolve station coordinates to boroughs
    unique_locations = list(station_coords.keys())
    unique_coords = [station_coords[loc_id] for loc_id in unique_locations]
    borough_results = coord_to_borough_bulk(unique_coords)
    station_borough: dict[int, str | None] = dict(zip(unique_locations, borough_results))

    # Group readings by borough
    borough_pm25: dict[str, list[float]] = defaultdict(list)
    borough_no2: dict[str, list[float]] = defaultdict(list)

    for reading in fresh_readings:
        location_id = reading.get("location_id")
        value = reading.get("value")
        param = reading.get("parameter", "")

        if value is None or location_id not in station_borough:
            continue

        bc = station_borough[location_id]
        if bc is None:
            continue

        if param == "pm25":
            borough_pm25[bc].append(value)
        elif param == "no2":
            borough_no2[bc].append(value)

    # Score each borough — weight formula by available parameters
    all_boroughs = set(borough_pm25.keys()) | set(borough_no2.keys())
    rows = []
    for bc in all_boroughs:
        has_pm25 = bc in borough_pm25
        has_no2 = bc in borough_no2

        pm25_avg = mean(borough_pm25[bc]) if has_pm25 else 0.0
        no2_avg = mean(borough_no2[bc]) if has_no2 else 0.0

        # Weight formula by available parameters instead of defaulting missing to 0
        if has_pm25 and has_no2:
            raw_ratio = (pm25_avg / 15.0) * 0.6 + (no2_avg / 25.0) * 0.4
        elif has_pm25:
            raw_ratio = pm25_avg / 15.0  # only PM2.5 available
        else:
            raw_ratio = no2_avg / 25.0  # only NO2 available

        # Exponential decay: ratio=0 -> 100, ratio=1.0 -> 22, ratio=2.0 -> 5
        normalised = _clamp(100.0 * math.exp(-1.5 * raw_ratio))

        rows.append(_make_row(bc, timestamp, "air_quality", raw_ratio, normalised, "openaq"))

    logger.info("Silver OpenAQ: %d borough rows (from %d fresh readings)", len(rows), len(fresh_readings))
    return rows


def _transform_sentiment_source(
    data: dict,
    source_name: str,
    text_field: str,
    timestamp: str,
) -> list[tuple]:
    """Transform a sentiment source (Reddit/BBC/Guardian) to silver rows.

    Scores text via the local sentiment model, then assigns the city-wide
    average to all 33 boroughs (these sources are London-wide, not
    borough-specific).

    metric_name: 'sentiment'
    normalised_score: (avg_sentiment + 1) * 50 maps [-1,1] to [0,100]
    """
    results = data.get("results", [])
    if not results:
        logger.warning("Silver %s: no results in bronze data", source_name)
        return []

    # Extract texts to score
    texts = []
    skipped = 0
    for item in results:
        text = None
        if text_field == "title":
            text = item.get("title")
        elif text_field == "description":
            text = item.get("description")
        elif text_field == "trailText":
            fields = item.get("fields", {})
            if isinstance(fields, dict):
                text = fields.get("trailText")
            else:
                skipped += 1
                logger.debug(
                    "Silver %s: unexpected fields type %s in article: %s",
                    source_name, type(fields).__name__,
                    str(item.get("webTitle", item.get("id", "?")))[:60],
                )
        if text and isinstance(text, str) and text.strip():
            texts.append(text.strip())
        else:
            skipped += 1

    if skipped:
        logger.info("Silver %s: %d/%d articles had no scorable text", source_name, skipped, len(results))

    if not texts:
        logger.warning("Silver %s: no scorable text found in %d results", source_name, len(results))
        return []

    # Score via local sentiment model
    scores = score_texts(texts)
    avg_sentiment = mean(scores)

    # Normalise [-1, 1] → [0, 100]
    raw_value = avg_sentiment
    normalised = _clamp((avg_sentiment + 1.0) * 50.0)

    # Assign city-wide score to all 33 boroughs
    rows = []
    for bc in BOROUGHS:
        rows.append(_make_row(bc, timestamp, "sentiment", raw_value, normalised, source_name))

    logger.info(
        "Silver %s: scored %d texts, avg=%.3f, normalised=%.1f → %d borough rows",
        source_name, len(texts), avg_sentiment, normalised, len(rows),
    )
    return rows


def _transform_reddit(data: dict, timestamp: str) -> list[tuple]:
    """Transform Reddit bronze data to silver sentiment rows."""
    return _transform_sentiment_source(data, "reddit", "title", timestamp)


def _transform_bbc(data: dict, timestamp: str) -> list[tuple]:
    """Transform BBC News bronze data to silver sentiment rows."""
    return _transform_sentiment_source(data, "bbc", "description", timestamp)


def _transform_guardian(data: dict, timestamp: str) -> list[tuple]:
    """Transform Guardian bronze data to silver sentiment rows."""
    return _transform_sentiment_source(data, "guardian", "trailText", timestamp)


# ---------------------------------------------------------------------------
# Main entry points — transform and load are separated
# ---------------------------------------------------------------------------

# Source name → transformer function
_SOURCES = [
    ("nhs_ae", _transform_nhs_ae),
    ("tfl", _transform_tfl),
    ("met_police", _transform_met_police),
    ("openaq", _transform_openaq),
    ("reddit", _transform_reddit),
    ("bbc", _transform_bbc),
    ("guardian", _transform_guardian),
]


def transform_all() -> list[tuple]:
    """Run silver transformations for all sources, return all rows.

    Reads the latest bronze file for each source, transforms it, and
    returns a flat list of row tuples ready for insertion.

    Returns:
        List of silver_metrics row tuples.
    """
    all_rows: list[tuple] = []

    for source_name, transformer in _SOURCES:
        loaded = _load_bronze(source_name)
        if loaded is None:
            continue

        data, timestamp = loaded
        try:
            rows = transformer(data, timestamp)
        except Exception as exc:
            logger.error("Silver transform failed for %s: %s", source_name, exc)
            continue

        all_rows.extend(rows)

    logger.info("Silver transform_all: %d total rows produced", len(all_rows))
    return all_rows


def load(con: duckdb.DuckDBPyConnection, rows: list[tuple]) -> int:
    """Insert silver rows into DuckDB.

    Args:
        con: An open DuckDB connection (tables must already exist via init_db).
        rows: List of silver_metrics row tuples from transform_all().

    Returns:
        Number of rows inserted.
    """
    if not rows:
        return 0

    con.executemany(
        """
        INSERT INTO silver_metrics
        (borough_code, borough_name, timestamp, metric_name, raw_value,
         normalised_score, source, ingested_at, pipeline_stage)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    logger.info("Silver load: %d rows inserted into DuckDB", len(rows))
    return len(rows)


def transform(con: duckdb.DuckDBPyConnection) -> int:
    """Convenience wrapper: transform all sources and load into DuckDB.

    Combines transform_all() + load() for backwards compatibility.

    Args:
        con: An open DuckDB connection (tables must already exist via init_db).

    Returns:
        Total number of rows inserted.
    """
    rows = transform_all()
    return load(con, rows)
