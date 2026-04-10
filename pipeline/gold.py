"""
Gold layer aggregator.

Reads Silver metrics from DuckDB, computes weighted composite health scores
per borough per cycle, writes to the DuckDB gold_scores table, and embeds
each row as a text description in ChromaDB for RAG retrieval.
Schema: (borough_code, borough_name, timestamp, air_score, transit_score,
         sentiment_score, immune_score, composite_score, ingested_at, pipeline_stage)
"""

import logging
import os
from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean

import duckdb

from pipeline.schemas import BOROUGHS

logger = logging.getLogger(__name__)

# Default equal weights: air, transit, sentiment, immune
_DEFAULT_WEIGHTS = (0.25, 0.25, 0.25, 0.25)


def _load_weights() -> tuple[float, float, float, float]:
    """Load composite score weights from SCORE_WEIGHTS env var.

    Format: 'air,transit,sentiment,immune' e.g. '0.25,0.25,0.25,0.25'.
    Falls back to equal weights on parse error.
    """
    raw = os.environ.get("SCORE_WEIGHTS", "")
    if not raw:
        return _DEFAULT_WEIGHTS
    try:
        parts = [float(x.strip()) for x in raw.split(",")]
        if len(parts) != 4 or any(w < 0 for w in parts):
            raise ValueError("need 4 non-negative floats")
        if sum(parts) <= 0:
            raise ValueError("weights must sum to > 0")
        return (parts[0], parts[1], parts[2], parts[3])
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

    # Get latest silver row per (borough, metric_name)
    latest = con.execute("""
        SELECT borough_code, borough_name, metric_name, source, normalised_score
        FROM (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY borough_code, metric_name, source
                       ORDER BY ingested_at DESC
                   ) AS rn
            FROM silver_metrics
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
    coverage = {"air": 0, "transit": 0, "sentiment": 0, "immune": 0}

    for borough_code in BOROUGHS:
        metrics = borough_data.get(borough_code, {})
        borough_name = borough_names.get(borough_code, BOROUGHS[borough_code]["name"])

        # Pivot: each sub-score is the average of its constituent metric_names
        air_score = mean(metrics["air_quality"]) if "air_quality" in metrics else None
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

        # Track coverage
        if air_score is not None:
            coverage["air"] += 1
        if transit_score is not None:
            coverage["transit"] += 1
        if sentiment_score is not None:
            coverage["sentiment"] += 1
        if immune_score is not None:
            coverage["immune"] += 1

        # Composite: weighted average, renormalised over present scores
        pairs = [
            (air_score, weights[0]),
            (transit_score, weights[1]),
            (sentiment_score, weights[2]),
            (immune_score, weights[3]),
        ]
        present = [(score, weight) for score, weight in pairs if score is not None]

        if not present:
            skipped.append(borough_code)
            continue

        total_weight = sum(w for _, w in present)
        composite = sum(s * w for s, w in present) / total_weight
        composite = max(0.0, min(100.0, composite))

        rows.append((
            borough_code,
            borough_name,
            now,
            air_score,
            transit_score,
            sentiment_score,
            immune_score,
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
        (borough_code, borough_name, timestamp, air_score, transit_score,
         sentiment_score, immune_score, composite_score, ingested_at, pipeline_stage)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )

    logger.info(
        "Gold: %d rows inserted — coverage: air=%d, transit=%d, sentiment=%d, immune=%d",
        len(rows), coverage["air"], coverage["transit"],
        coverage["sentiment"], coverage["immune"],
    )
    return len(rows)
