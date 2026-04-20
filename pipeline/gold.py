"""
Gold layer aggregator.

Reads Silver metrics from DuckDB, computes weighted composite health scores
per borough per cycle, writes to the DuckDB gold_scores table, and embeds
each row as a text description in ChromaDB for RAG retrieval.
Schema: (borough_code, borough_name, timestamp, air_score, transit_score,
         sentiment_score, immune_score, green_space_score,
         green_space_access_score, composite_score,
         ingested_at, pipeline_stage)

green_space_access_score is a ward-population-weighted variant of green cover
(see pipeline/silver.py:_transform_green_space). It is surfaced alongside the
raw coverage score but intentionally NOT folded into the composite — the
headline composite stays anchored on raw coverage so historical comparisons
and equity-residual computations regress against a stable target.
"""

import functools
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean

import duckdb

from pipeline.schemas import BOROUGHS

logger = logging.getLogger(__name__)

# Default equal weights: air, transit, sentiment, immune, green_space
_DEFAULT_WEIGHTS = (0.20, 0.20, 0.20, 0.20, 0.20)


@functools.lru_cache(maxsize=1)
def _load_weights() -> tuple[float, float, float, float, float]:
    """Load composite score weights from SCORE_WEIGHTS env var.

    Format: 'air,transit,sentiment,immune,green_space' e.g. '0.20,0.20,0.20,0.20,0.20'.
    Falls back to equal weights on parse error.

    Result is cached for the lifetime of the process — the env var is
    expected to be set once at startup and not changed at runtime.
    """
    raw = os.environ.get("SCORE_WEIGHTS", "")
    if not raw:
        return _DEFAULT_WEIGHTS
    try:
        parts = [float(x.strip()) for x in raw.split(",")]
        if len(parts) != 5 or any(w < 0 for w in parts):
            raise ValueError("need 5 non-negative floats")
        if sum(parts) <= 0:
            raise ValueError("weights must sum to > 0")
        if abs(sum(parts) - 1.0) > 0.01:
            logger.warning("SCORE_WEIGHTS sum to %.2f, not 1.0 — scores will be renormalised", sum(parts))
        return (parts[0], parts[1], parts[2], parts[3], parts[4])
    except (ValueError, TypeError) as exc:
        logger.warning("Gold: invalid SCORE_WEIGHTS '%s': %s — using defaults", raw, exc)
        return _DEFAULT_WEIGHTS


def aggregate(con: duckdb.DuckDBPyConnection) -> int:
    """Aggregate silver metrics into gold health scores per borough.

    Queries the latest silver_metrics row per (borough_code, metric_name),
    pivots into per-borough sub-scores (air, transit, sentiment, immune),
    computes a weighted composite, and inserts into gold_scores.

    Boroughs with no silver data at all are skipped (no row inserted).
    Missing sub-scores are NULL; composite is renormalised over present scores.

    Args:
        con: An open DuckDB connection (tables must already exist via init_db).

    Returns:
        Number of gold_scores rows inserted.
    """
    weights = _load_weights()
    now = datetime.now(timezone.utc).isoformat()

    # Get latest silver row per (borough, metric_name), restricted to rows
    # ingested within the last 48 hours so that dead sources drop out
    # automatically rather than persisting stale scores indefinitely.
    latest = con.execute("""
        SELECT borough_code, borough_name, metric_name, source, normalised_score
        FROM (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY borough_code, metric_name, source
                       ORDER BY ingested_at DESC
                   ) AS rn
            FROM silver_metrics
            WHERE ingested_at > CURRENT_TIMESTAMP - INTERVAL 48 HOUR
        )
        WHERE rn = 1
    """).fetchall()

    if not latest:
        logger.warning("Gold: no silver metrics found — skipping aggregation")
        return 0

    # Group by borough: {borough_code: {metric_name: [normalised_scores]}}
    borough_data: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    borough_names: dict[str, str] = {}

    for borough_code, borough_name, metric_name, _source, normalised_score in latest:
        borough_data[borough_code][metric_name].append(normalised_score)
        borough_names[borough_code] = borough_name

    # Build gold rows
    rows: list[tuple] = []
    skipped: list[str] = []

    # Coverage counters for logging
    coverage = {"air": 0, "air_modelled": 0, "transit": 0, "sentiment": 0, "immune": 0, "green_space": 0, "green_space_access": 0}

    for borough_code in BOROUGHS:
        metrics = borough_data.get(borough_code, {})
        borough_name = borough_names.get(borough_code, BOROUGHS[borough_code]["name"])

        # Pivot: each sub-score is the average of its constituent metric_names
        air_score = mean(metrics["air_quality"]) if "air_quality" in metrics else None
        air_quality_modelled_score = (
            mean(metrics["air_quality_modelled"]) if "air_quality_modelled" in metrics else None
        )
        transit_score = mean(metrics["transit"]) if "transit" in metrics else None

        # Sentiment: average across up to 3 sources (reddit, bbc, guardian)
        sentiment_scores = metrics.get("sentiment", [])
        sentiment_score = mean(sentiment_scores) if sentiment_scores else None

        # Immune: average of crime + nhs_ae
        immune_parts = []
        if "crime" in metrics:
            immune_parts.extend(metrics["crime"])
        if "nhs_ae" in metrics:
            immune_parts.extend(metrics["nhs_ae"])
        immune_score = mean(immune_parts) if immune_parts else None

        # Green space (Skin organ) — raw coverage + ward-pop-weighted access variant
        green_space_score = mean(metrics["green_space"]) if "green_space" in metrics else None
        green_space_access_score = (
            mean(metrics["green_space_access"]) if "green_space_access" in metrics else None
        )

        # Track coverage
        if air_score is not None:
            coverage["air"] += 1
        if air_quality_modelled_score is not None:
            coverage["air_modelled"] += 1
        if transit_score is not None:
            coverage["transit"] += 1
        if sentiment_score is not None:
            coverage["sentiment"] += 1
        if immune_score is not None:
            coverage["immune"] += 1
        if green_space_score is not None:
            coverage["green_space"] += 1
        if green_space_access_score is not None:
            coverage["green_space_access"] += 1

        # Composite: weighted average, renormalised over present scores.
        # NOTE: composite uses the RAW green_space_score (coverage), not the
        # access-weighted variant — see module docstring.
        pairs = [
            (air_score, weights[0]),
            (transit_score, weights[1]),
            (sentiment_score, weights[2]),
            (immune_score, weights[3]),
            (green_space_score, weights[4]),
        ]
        present = [(score, weight) for score, weight in pairs if score is not None]

        if not present:
            skipped.append(borough_code)
            continue

        total_weight = sum(w for _, w in present)
        if total_weight == 0:
            skipped.append(borough_code)
            continue
        composite = sum(s * w for s, w in present) / total_weight
        composite = max(0.0, min(100.0, composite))

        rows.append((
            borough_code,
            borough_name,
            now,
            air_score,
            air_quality_modelled_score,
            transit_score,
            sentiment_score,
            immune_score,
            green_space_score,
            green_space_access_score,
            round(composite, 2),
            now,
            "gold",
        ))

    if skipped:
        logger.warning(
            "Gold: %d borough(s) skipped (no silver data): %s",
            len(skipped), skipped,
        )

    if not rows:
        logger.warning("Gold: no rows to insert")
        return 0

    con.executemany(
        """
        INSERT INTO gold_scores
        (borough_code, borough_name, timestamp, air_score, air_quality_modelled_score,
         transit_score, sentiment_score, immune_score, green_space_score,
         green_space_access_score, composite_score, ingested_at, pipeline_stage)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )

    logger.info(
        "Gold: %d rows inserted — coverage: air=%d, air_modelled=%d, transit=%d, sentiment=%d, immune=%d, green_space=%d, green_space_access=%d",
        len(rows), coverage["air"], coverage["air_modelled"], coverage["transit"],
        coverage["sentiment"], coverage["immune"],
        coverage["green_space"], coverage["green_space_access"],
    )
    return len(rows)
