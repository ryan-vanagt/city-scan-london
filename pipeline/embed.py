"""
Embedding step: writes gold-layer borough scores to ChromaDB.

Called after gold.aggregate() in the pipeline runner. Each gold_scores row
is converted to a natural language description and upserted into ChromaDB
with full metadata for RAG retrieval by the Doctor Agent.

This step is fault-tolerant: if ChromaDB is unavailable, the pipeline
continues and logs a warning. DuckDB gold_scores remain the source of truth.
"""

import logging

import duckdb

logger = logging.getLogger(__name__)


def _format_score(value: float | None) -> str:
    """Format a score for the document text, using 'N/A' for NULL."""
    return f"{value:.2f}" if value is not None else "N/A"


def _row_to_document(row: tuple) -> str:
    """Convert a gold_scores row to a natural language description.

    Args:
        row: (borough_code, borough_name, timestamp, air_score,
              air_quality_modelled_score, transit_score, sentiment_score,
              immune_score, green_space_score, green_space_access_score,
              composite_score, ingested_at)

    Returns:
        Human-readable text description suitable for embedding.
    """
    (code, name, ts, air, air_modelled, transit, sentiment, immune,
     green_space, green_space_access, composite, ingested_at) = row
    date_str = str(ts)[:10]
    return (
        f"{name} ({code}) scored {composite:.2f} overall on {date_str}. "
        f"Air: {_format_score(air)} (live OpenAQ), "
        f"{_format_score(air_modelled)} (LAEI 2022 modelled), "
        f"Transit: {_format_score(transit)}, "
        f"Sentiment: {_format_score(sentiment)}, Immune: {_format_score(immune)}, "
        f"Green Space: {_format_score(green_space)} (coverage), "
        f"{_format_score(green_space_access)} (access-weighted by ward population) "
        f"(data from {ingested_at})"
    )


def _row_to_id(row: tuple) -> str:
    """Generate a deterministic ChromaDB document ID from a gold_scores row.

    Format: '{borough_code}_{YYYY-MM-DD}' — enables upsert deduplication
    so re-running the pipeline on the same day overwrites rather than duplicates.
    """
    code = row[0]
    date_str = str(row[2])[:10]
    return f"{code}_{date_str}"


def _row_to_metadata(row: tuple) -> dict:
    """Extract metadata dict from a gold_scores row.

    ChromaDB metadata values cannot be None, so NULL scores are omitted.
    """
    (code, name, ts, air, air_modelled, transit, sentiment, immune,
     green_space, green_space_access, composite) = row[:11]
    date_str = str(ts)[:10]
    meta: dict = {
        "borough_code": code,
        "borough_name": name,
        "timestamp": date_str,
        "composite_score": composite,
    }
    if air is not None:
        meta["air_score"] = air
    if air_modelled is not None:
        meta["air_quality_modelled_score"] = air_modelled
    if transit is not None:
        meta["transit_score"] = transit
    if sentiment is not None:
        meta["sentiment_score"] = sentiment
    if immune is not None:
        meta["immune_score"] = immune
    if green_space is not None:
        meta["green_space_score"] = green_space
    if green_space_access is not None:
        meta["green_space_access_score"] = green_space_access
    return meta


def embed_gold_scores(con: duckdb.DuckDBPyConnection) -> int:
    """Embed the latest gold_scores rows into ChromaDB.

    Queries the most recent gold_scores row per borough from DuckDB,
    converts each to a text description, and upserts into ChromaDB.
    Uses upsert to handle re-runs gracefully (same ID = overwrite).

    This function is fault-tolerant: if ChromaDB is unavailable or any
    error occurs, it logs a warning and returns 0.

    Args:
        con: An open DuckDB connection with gold_scores populated.

    Returns:
        Number of documents upserted into ChromaDB, or 0 on failure.
    """
    try:
        from pipeline.chroma_client import get_collection
    except Exception as exc:
        logger.warning("Embed: failed to import ChromaDB client: %s — skipping", exc)
        return 0

    rows = con.execute("""
        SELECT borough_code, borough_name, timestamp,
               air_score, air_quality_modelled_score,
               transit_score, sentiment_score,
               immune_score, green_space_score, green_space_access_score,
               composite_score, ingested_at
        FROM (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY borough_code
                       ORDER BY ingested_at DESC
                   ) AS rn
            FROM gold_scores
            WHERE ingested_at > CURRENT_TIMESTAMP - INTERVAL 48 HOUR
        )
        WHERE rn = 1
    """).fetchall()

    if not rows:
        logger.warning("Embed: no gold_scores rows found — skipping")
        return 0

    import time

    ids = [_row_to_id(r) for r in rows]
    documents = [_row_to_document(r) for r in rows]
    metadatas = [_row_to_metadata(r) for r in rows]

    # Retry up to 60s — ChromaDB may still be booting on cold start
    for attempt in range(1, 7):
        try:
            collection = get_collection()
            collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
            )
            logger.info(
                "Embed: %d documents upserted to ChromaDB collection 'gold_scores'",
                len(rows),
            )
            return len(rows)
        except Exception as exc:
            if attempt < 6:
                logger.warning(
                    "Embed: ChromaDB not ready (attempt %d/6): %s — retrying in 10s",
                    attempt, exc,
                )
                # Reset cached client so next attempt reconnects
                from pipeline.chroma_client import close_client
                close_client()
                time.sleep(10)
            else:
                logger.warning(
                    "Embed: ChromaDB upsert failed after 6 attempts: %s — skipping "
                    "(gold_scores in DuckDB unaffected)",
                    exc,
                )
                return 0

    return 0  # should not reach here, but safety fallback
