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
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from urllib.parse import urlparse

import duckdb

from pipeline.schemas import (
    BOROUGHS,
    LINE_TO_BOROUGHS,
    OPENAQ_STATION_BOROUGHS,
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
    # Returns only the most recent bronze file. If the latest file is corrupt, earlier good files are ignored.
    """Return the most recent bronze JSON file for a source, or None."""
    source_dir = BRONZE_BASE / source
    if not source_dir.exists():
        return None
    files = sorted(f for f in source_dir.glob("*.json") if not f.name.startswith("_"))
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
        # Filename format: YYYYMMDD_HHMMSS_ffffff.json or YYYYMMDD_HHMMSS.json
        stem = path.stem
        for fmt in ("%Y%m%d_%H%M%S_%f", "%Y%m%d_%H%M%S"):
            try:
                dt = datetime.strptime(stem, fmt).replace(tzinfo=timezone.utc)
                timestamp = dt.isoformat()
                break
            except ValueError:
                continue
        else:
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
        # _make_row already calls _clamp internally; no need to clamp here too.
        rows.append(_make_row(bc, timestamp, "nhs_ae", avg_pct, avg_pct, "nhs_ae"))

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
        # TfL severity: 0 (worst) to 10 (Good Service); 11-13 are rare
        # informational statuses — cap at 10 so they don't clamp to 100
        normalised = _clamp(min(min_sev, 10) * 10.0)
        rows.append(_make_row(bc, timestamp, "transit", raw_value, normalised, "tfl"))

    logger.info("Silver TfL: %d borough rows", len(rows))
    return rows


def _transform_met_police(data: dict, timestamp: str) -> list[tuple]:
    """Transform Met Police crime bronze data to silver rows.

    metric_name: 'crime'
    raw_value: crimes per 1,000 residents (per-capita)
    normalised_score: min-max inverted (lower crime rate = higher score)
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

    if len(borough_counts) < 3:
        logger.warning(
            "Silver Met Police: only %d borough(s) with data — skipping cycle "
            "(min-max normalisation unreliable with < 3 boroughs)",
            len(borough_counts),
        )
        return []

    # Convert raw counts to per-capita rates (crimes per 1,000 residents).
    # This prevents high-footfall boroughs (Westminster, City of London) from
    # always scoring worst due to volume rather than resident risk.
    borough_rates: dict[str, float] = {}
    for bc, count in borough_counts.items():
        pop = BOROUGHS[bc].get("population")
        if pop and pop > 0:
            borough_rates[bc] = (count / pop) * 1000
        else:
            logger.warning(
                "Silver Met Police: no population for %s — excluding from scoring", bc,
            )
            continue

    # Winsorise at 95th percentile to prevent non-residential borough outliers
    # (e.g. City of London: 15k residents, 500k daily workers) from compressing
    # the score range for all other boroughs.
    rates_sorted = sorted(borough_rates.values())
    p95 = rates_sorted[int(len(rates_sorted) * 0.95)]
    borough_rates = {bc: min(rate, p95) for bc, rate in borough_rates.items()}

    # Min-max normalise, inverted: fewer crimes per capita = higher score
    rates = list(borough_rates.values())
    min_rate = min(rates)
    max_rate = max(rates)
    if max_rate == min_rate:
        logger.warning(
            "Silver Met Police: all %d boroughs have identical crime rate (%.1f) — "
            "min-max range is zero; all boroughs will score 100 this cycle",
            len(borough_rates), min_rate,
        )
    range_rate = max_rate - min_rate if max_rate != min_rate else 1.0

    rows = []
    for bc, rate in borough_rates.items():
        raw_value = round(rate, 2)
        normalised = _clamp(100.0 * (1.0 - (rate - min_rate) / range_rate))
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

    # Filter stale and invalid readings
    cutoff = datetime.now(timezone.utc) - timedelta(days=_MAX_READING_AGE_DAYS)
    fresh_readings = []
    stale_count = 0
    negative_count = 0
    for reading in readings:
        # Filter negative values (sensor calibration errors)
        value = reading.get("value")
        if value is not None and value < 0:
            negative_count += 1
            continue

        dt_str = reading.get("datetime_utc")
        if dt_str:
            try:
                dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                if dt < cutoff:
                    stale_count += 1
                    continue
            except (ValueError, TypeError):
                stale_count += 1
                continue  # unparseable datetime treated as stale
        fresh_readings.append(reading)

    if negative_count:
        logger.info("Silver OpenAQ: filtered %d negative readings (sensor errors)", negative_count)

    if stale_count:
        logger.info(
            "Silver OpenAQ: filtered %d stale readings (>%d days old), %d fresh remain",
            stale_count, _MAX_READING_AGE_DAYS, len(fresh_readings),
        )

    if not fresh_readings:
        logger.warning("Silver OpenAQ: no fresh readings after filtering")
        return []

    # Build station coordinate lookup for stations not in the pre-cache
    station_coords: dict[int, tuple[float, float]] = {}
    station_borough: dict[int, str | None] = {}

    cache_hits = 0
    for station in stations:
        sid = station.get("id")
        if sid is None:
            continue
        # Check pre-cached mapping first (generated by scripts/generate_geo_mappings.py)
        cached = OPENAQ_STATION_BOROUGHS.get(str(sid))
        if cached is not None or str(sid) in OPENAQ_STATION_BOROUGHS:
            station_borough[sid] = cached
            cache_hits += 1
        else:
            coords = station.get("coordinates")
            if coords and coords.get("latitude") is not None:
                station_coords[sid] = (
                    coords["latitude"],
                    coords["longitude"],
                )

    if cache_hits:
        logger.info("OpenAQ silver: %d/%d stations resolved from pre-cache", cache_hits, len(stations))

    # Bulk-resolve remaining station coordinates via live postcodes.io
    if station_coords:
        unique_locations = list(station_coords.keys())
        unique_coords = [station_coords[loc_id] for loc_id in unique_locations]
        borough_results = coord_to_borough_bulk(unique_coords)
        for loc_id, bc in zip(unique_locations, borough_results):
            station_borough[loc_id] = bc

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
            who_ratio = (pm25_avg / 15.0) * 0.6 + (no2_avg / 25.0) * 0.4
            # Store the primary pollutant measurement as raw_value (PM2.5 takes precedence)
            raw_value = pm25_avg
        elif has_pm25:
            who_ratio = pm25_avg / 15.0  # only PM2.5 available
            raw_value = pm25_avg
        else:
            who_ratio = no2_avg / 25.0  # only NO2 available
            raw_value = no2_avg

        # Exponential decay: ratio=0 -> 100, ratio=1.0 -> 22, ratio=2.0 -> 5
        normalised = _clamp(100.0 * math.exp(-1.5 * who_ratio))

        rows.append(_make_row(bc, timestamp, "air_quality", raw_value, normalised, "openaq"))

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


def _transform_green_space(data: dict, timestamp: str) -> list[tuple]:
    """Transform green space bronze data to silver rows.

    metric_name: 'green_space'
    raw_value: green cover percentage (e.g. 42.9)
    normalised_score: min-max normalisation across the 33 boroughs
    """
    results = data.get("results", [])
    if not results:
        logger.warning("Silver green_space: no results in bronze data")
        return []

    # Collect valid borough data
    borough_pcts: dict[str, float] = {}
    for item in results:
        bc = item.get("borough_code")
        pct = item.get("green_pct")
        if bc and bc in BOROUGHS and pct is not None:
            borough_pcts[bc] = float(pct)

    if not borough_pcts:
        logger.warning("Silver green_space: no valid borough data")
        return []

    # Min-max normalisation across all boroughs
    pcts = list(borough_pcts.values())
    min_pct = min(pcts)
    max_pct = max(pcts)
    range_pct = max_pct - min_pct

    if range_pct == 0:
        logger.warning(
            "Silver green_space: all %d boroughs have identical green cover (%.1f%%) — "
            "min-max range is zero; all boroughs will score 100",
            len(borough_pcts), min_pct,
        )

    rows = []
    for bc, pct in borough_pcts.items():
        raw_value = pct
        normalised = _clamp((pct - min_pct) / range_pct * 100.0) if range_pct > 0 else 100.0
        rows.append(_make_row(bc, timestamp, "green_space", raw_value, normalised, "green_space"))

    logger.info("Silver green_space: %d borough rows", len(rows))
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
    ("green_space", _transform_green_space),
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
        try:
            loaded = _load_bronze(source_name)
            if loaded is None:
                continue

            data, timestamp = loaded
            rows = transformer(data, timestamp)
        except Exception as exc:
            logger.error("Silver transform failed for %s: %s", source_name, exc)
            continue

        all_rows.extend(rows)

    logger.info("Silver transform_all: %d total rows produced", len(all_rows))
    return all_rows


def load(con: duckdb.DuckDBPyConnection, rows: list[tuple]) -> int:
    """Insert silver rows into DuckDB.

    Logs a warning if any rows contain data older than 24 hours — the data
    is still inserted (stale data is better than no data), but the operator
    should be aware that source freshness may be degraded.

    Args:
        con: An open DuckDB connection (tables must already exist via init_db).
        rows: List of silver_metrics row tuples from transform_all().

    Returns:
        Number of rows inserted.
    """
    if not rows:
        return 0

    # Staleness check: column index 2 is the 'timestamp' field (source data time)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    stale_sources: set[str] = set()
    for row in rows:
        ts_str = row[2]  # timestamp (ISO 8601 string)
        source = row[6]  # source name
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if ts < cutoff:
                stale_sources.add(source)
        except (ValueError, TypeError, AttributeError):
            logger.debug("Unparseable timestamp in silver staleness check: %s", ts_str)

    if stale_sources:
        logger.warning(
            "Silver load: data from %d source(s) is older than 24h — "
            "pipeline may not have run recently: %s",
            len(stale_sources), sorted(stale_sources),
        )

    # Deduplicate: delete existing rows for the same (source, timestamp) pairs
    # before inserting — prevents duplicate rows on pipeline re-runs.
    sources_timestamps: set[tuple[str, str]] = set()
    for row in rows:
        sources_timestamps.add((row[6], row[2]))  # (source, timestamp)
    for source, ts in sources_timestamps:
        con.execute(
            "DELETE FROM silver_metrics WHERE source = ? AND timestamp = ?",
            [source, ts],
        )

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


# ---------------------------------------------------------------------------
# Silver detail layer — contextual rows for agent queries
# ---------------------------------------------------------------------------

_ALLOWED_URL_DOMAINS = {"theguardian.com", "bbc.co.uk", "reddit.com", "bbc.com"}


def _sanitise_text(text: str | None, max_len: int = 500) -> str | None:
    """Sanitise text from external APIs before storing in detail tables."""
    if text is None:
        return None
    text = text[:max_len]
    # Strip null bytes and control characters (keep \n, \t, \r)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    return text


def _validate_url(url: str | None) -> str | None:
    """Only store URLs from known source domains."""
    if url is None:
        return None
    parsed = urlparse(url)
    domain = parsed.netloc.lower().removeprefix("www.")
    if not any(domain.endswith(d) for d in _ALLOWED_URL_DOMAINS):
        return None
    return url


def _detail_met_police(data: dict, timestamp: str) -> list[tuple]:
    """Extract per-crime detail rows from Met Police bronze data."""
    rows: list[tuple] = []
    now = datetime.now(timezone.utc).isoformat()
    for crime in data.get("results", []):
        bc = crime.get("borough_code")
        if not bc or bc not in BOROUGHS:
            continue
        category = crime.get("category", "unknown")
        location = crime.get("location") or {}
        street = (location.get("street") or {}).get("name") if isinstance(location, dict) else None
        rows.append((
            bc,
            BOROUGHS[bc]["name"],
            timestamp,
            "met_police",
            _sanitise_text(category, 100),
            _sanitise_text(category.replace("-", " ").title()),
            1.0,
            _sanitise_text(street),
            now,
        ))
    logger.info("Silver detail met_police: %d rows", len(rows))
    return rows


def _detail_tfl(data: dict, timestamp: str) -> list[tuple]:
    """Extract per-line per-borough detail rows from TfL bronze data."""
    rows: list[tuple] = []
    now = datetime.now(timezone.utc).isoformat()
    for line in data.get("results", []):
        line_id = line.get("id", "")
        statuses = line.get("lineStatuses", [])
        if not statuses:
            continue
        status = statuses[0]
        severity = status.get("statusSeverity", 0)
        description = status.get("statusSeverityDescription", "Unknown")
        reason = status.get("reason", "")
        for bc in LINE_TO_BOROUGHS.get(line_id, []):
            if bc not in BOROUGHS:
                continue
            rows.append((
                bc,
                BOROUGHS[bc]["name"],
                timestamp,
                "tfl",
                _sanitise_text(line_id, 50),
                _sanitise_text(description),
                float(severity),
                _sanitise_text(reason) if reason else None,
                now,
            ))
    logger.info("Silver detail tfl: %d rows", len(rows))
    return rows


def _detail_openaq(data: dict, timestamp: str) -> list[tuple]:
    """Extract per-station per-reading detail rows from OpenAQ bronze data."""
    rows: list[tuple] = []
    now = datetime.now(timezone.utc).isoformat()
    cutoff = datetime.now(timezone.utc) - timedelta(days=_MAX_READING_AGE_DAYS)

    # Build station lookup
    stations = {s["id"]: s for s in data.get("stations", []) if "id" in s}

    for reading in data.get("readings", []):
        location_id = reading.get("location_id")
        value = reading.get("value")
        parameter = reading.get("parameter", "")

        # Skip invalid
        if value is None or value < 0:
            continue

        # Skip stale
        dt_str = reading.get("datetime_utc", "")
        if dt_str:
            try:
                dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                if dt < cutoff:
                    continue
            except (ValueError, TypeError):
                continue  # Skip unparseable timestamps (align with main transform)

        # Resolve borough
        bc = OPENAQ_STATION_BOROUGHS.get(str(location_id))
        if not bc:
            station = stations.get(location_id, {})
            coords = station.get("coordinates", {})
            lat = coords.get("latitude")
            lng = coords.get("longitude")
            if lat is not None and lng is not None:
                bc = coord_to_borough(lat, lng)
        if not bc or bc not in BOROUGHS:
            continue

        station_name = stations.get(location_id, {}).get("name", f"Station {location_id}")
        rows.append((
            bc,
            BOROUGHS[bc]["name"],
            timestamp,
            "openaq",
            _sanitise_text(parameter, 50),
            _sanitise_text(station_name),
            float(value),
            None,
            now,
        ))
    logger.info("Silver detail openaq: %d rows", len(rows))
    return rows


def _detail_nhs_ae(data: dict, timestamp: str) -> list[tuple]:
    """Extract per-trust per-borough detail rows from NHS A&E bronze data."""
    rows: list[tuple] = []
    now = datetime.now(timezone.utc).isoformat()
    period = data.get("period", "")
    for trust in data.get("results", []):
        org_code = trust.get("org_code", "")
        org_name = trust.get("org_name", "")
        total = trust.get("total_type1_attendances", 0)
        over_4hrs = trust.get("over_4hrs_type1", 0)
        if total <= 0:
            continue
        pct = (total - over_4hrs) / total * 100.0
        for bc in TRUST_TO_BOROUGHS.get(org_code, []):
            if bc not in BOROUGHS:
                continue
            rows.append((
                bc,
                BOROUGHS[bc]["name"],
                timestamp,
                "nhs_ae",
                _sanitise_text(org_code, 20),
                _sanitise_text(org_name),
                pct,
                _sanitise_text(period),
                now,
            ))
    logger.info("Silver detail nhs_ae: %d rows", len(rows))
    return rows


def _detail_green_space(data: dict, timestamp: str) -> list[tuple]:
    """Extract per-ward green cover detail rows from green space bronze data."""
    rows: list[tuple] = []
    now = datetime.now(timezone.utc).isoformat()

    for ward in data.get("wards", []):
        bc = ward.get("borough_code", "")
        if bc not in BOROUGHS:
            continue
        rows.append((
            bc,
            BOROUGHS[bc]["name"],
            timestamp,
            "green_space",
            "green_cover",
            _sanitise_text(ward.get("ward_name", "")),
            ward.get("green_pct", 0.0),
            _sanitise_text(ward.get("ward_code", "")),
            now,
        ))

    logger.info("Silver detail green_space: %d ward rows", len(rows))
    return rows


def _headlines_detail(
    data: dict, source_name: str, timestamp: str,
) -> list[tuple]:
    """Extract per-headline rows with individual sentiment scores."""
    now = datetime.now(timezone.utc).isoformat()
    items = data.get("results", [])

    # Extract titles and URLs per source
    titles: list[str] = []
    urls: list[str | None] = []
    for item in items:
        if source_name == "guardian":
            title = item.get("fields", {}).get("headline", item.get("webTitle", ""))
            url = item.get("webUrl")
        elif source_name == "bbc":
            title = item.get("title", "")
            url = item.get("link")
        elif source_name == "reddit":
            title = item.get("title", "")
            permalink = item.get("permalink")
            url = permalink if permalink and permalink.startswith("http") else (f"https://www.reddit.com{permalink}" if permalink else None)
        else:
            continue
        if not title or not isinstance(title, str):
            continue
        titles.append(title)
        urls.append(url)

    if not titles:
        return []

    # Score each title individually
    scores = score_texts(titles)

    rows: list[tuple] = []
    for title, url, score in zip(titles, urls, scores):
        rows.append((
            timestamp,
            source_name,
            _sanitise_text(title, 300),
            _validate_url(url),
            float(score),
            now,
        ))
    logger.info("Silver headlines %s: %d rows", source_name, len(rows))
    return rows


def transform_all_detail() -> tuple[list[tuple], list[tuple]]:
    """Extract contextual detail rows from bronze data for agent queries.

    Returns:
        Tuple of (detail_rows, headline_rows).
    """
    detail_rows: list[tuple] = []
    headline_rows: list[tuple] = []

    # Borough-scoped detail
    detail_sources = [
        ("met_police", _detail_met_police),
        ("tfl", _detail_tfl),
        ("openaq", _detail_openaq),
        ("nhs_ae", _detail_nhs_ae),
        ("green_space", _detail_green_space),
    ]
    for source_name, extractor in detail_sources:
        try:
            loaded = _load_bronze(source_name)
            if loaded is None:
                continue
            data, ts = loaded
            detail_rows.extend(extractor(data, ts))
        except Exception:
            logger.error(
                "Silver detail extraction failed for %s", source_name, exc_info=True,
            )

    # Headlines with per-title sentiment
    for source_name in ("reddit", "bbc", "guardian"):
        try:
            loaded = _load_bronze(source_name)
            if loaded is None:
                continue
            data, ts = loaded
            headline_rows.extend(_headlines_detail(data, source_name, ts))
        except Exception:
            logger.error(
                "Silver headlines extraction failed for %s", source_name, exc_info=True,
            )

    logger.info(
        "Silver detail total: %d detail rows, %d headline rows",
        len(detail_rows), len(headline_rows),
    )
    return detail_rows, headline_rows


def load_detail(
    con: duckdb.DuckDBPyConnection,
    detail_rows: list[tuple],
    headline_rows: list[tuple],
) -> tuple[int, int]:
    """Insert detail and headline rows into DuckDB.

    Deletes existing rows for the same source+timestamp before inserting
    to prevent duplication on repeated pipeline runs.
    """
    d_count = 0
    h_count = 0
    if detail_rows:
        # Deduplicate: collect unique (source, timestamp) pairs and delete old rows
        seen = {(r[3], r[2]) for r in detail_rows}  # (source, timestamp)
        for source, ts in seen:
            con.execute(
                "DELETE FROM silver_detail WHERE source = ? AND timestamp = ?",
                [source, ts],
            )
        con.executemany(
            """INSERT INTO silver_detail
            (borough_code, borough_name, timestamp, source, category, label,
             value, detail_text, ingested_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            detail_rows,
        )
        d_count = len(detail_rows)
    if headline_rows:
        seen = {(r[1], r[0]) for r in headline_rows}  # (source, timestamp)
        for source, ts in seen:
            con.execute(
                "DELETE FROM silver_headlines WHERE source = ? AND timestamp = ?",
                [source, ts],
            )
        con.executemany(
            """INSERT INTO silver_headlines
            (timestamp, source, title, url, sentiment_score, ingested_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            headline_rows,
        )
        h_count = len(headline_rows)
    logger.info("Silver detail load: %d detail, %d headlines inserted", d_count, h_count)
    return d_count, h_count
