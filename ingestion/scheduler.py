"""
APScheduler entry point for the ingestion service.

Runs all data source collectors on their respective schedules, then triggers
the full Bronze -> Silver -> Gold pipeline chain after each fetch cycle.

Schedule:
  - Hourly at :00  — fast sources (OpenAQ, TfL, Guardian, BBC, Reddit)
  - Daily  03:00 UTC — silver retention cleanup (rows older than 90 days)
  - Daily  06:05 UTC — slow sources (Met Police, NHS A&E) — data updates monthly
  - Daily  09:30 UTC — bulletin generation via LLM (after 09:00 pipeline completes)

On startup, runs a full pipeline cycle (all sources) so that the first
``docker compose up`` populates the database immediately.
"""

import logging
import os
import signal
import shutil
import sys
import threading
from pathlib import Path
from types import ModuleType

import duckdb
from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Project root & env
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

from agents.bulletin import generate_bulletin  # noqa: E402
from agents.logging_db import ensure_bulletin_logs_table  # noqa: E402
from ingestion.sources import bbc, green_space, guardian, met_police, nhs_ae, openaq, reddit, tfl  # noqa: E402
from pipeline import bronze, gold, silver  # noqa: E402
from pipeline.embed import embed_gold_scores  # noqa: E402
from pipeline.schemas import init_db  # noqa: E402

# ---------------------------------------------------------------------------
# Source groups
# ---------------------------------------------------------------------------
FAST_SOURCES: dict[str, ModuleType] = {
    "openaq": openaq,
    "tfl": tfl,
    "guardian": guardian,
    "bbc": bbc,
    "reddit": reddit,
}

SLOW_SOURCES: dict[str, ModuleType] = {
    "met_police": met_police,
    "nhs_ae": nhs_ae,
    "green_space": green_space,
}

DB_PATH = str(PROJECT_ROOT / "data" / "cityscan.duckdb")
DB_READ_PATH = str(PROJECT_ROOT / "data" / "cityscan_read.duckdb")

_db_write_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Pipeline helpers
# ---------------------------------------------------------------------------


def _fetch_sources(sources: dict[str, ModuleType]) -> None:
    """Fetch and save bronze data for the given source modules.

    Individual source failures are logged and skipped so that partial data
    still flows through the Silver/Gold chain.
    """
    for name, module in sources.items():
        try:
            data = module.fetch()
            path = bronze.save(name, data)
            bronze.cleanup(name)
            logger.info("Bronze: saved %s to %s", name, path)
        except Exception as exc:
            logger.error("Bronze fetch failed for %s: %s — skipping", name, exc)


def _connect_with_retry(path: str, max_attempts: int = 6, base_delay: float = 5.0):
    """Open a write-mode DuckDB connection, retrying if locked by another process."""
    for attempt in range(1, max_attempts + 1):
        try:
            return duckdb.connect(path)
        except (duckdb.IOException, duckdb.ConnectionException) as exc:
            if attempt == max_attempts:
                raise
            delay = base_delay * attempt
            logger.warning(
                "DuckDB locked (attempt %d/%d): %s — retrying in %.0fs",
                attempt, max_attempts, exc, delay,
            )
            import time
            time.sleep(delay)


def _release_api_read_lock() -> None:
    """Ask the API service to close its read-only DuckDB connection.

    The API holds a persistent read-only connection that blocks DuckDB
    write locks. This sends a POST to the API's internal reset endpoint
    so ingestion can acquire the write lock.
    """
    import urllib.request
    import time as _time
    try:
        req = urllib.request.Request("http://api:8000/internal/reset-db", method="POST")
        internal_token = os.environ.get("INTERNAL_TOKEN", "")
        if internal_token:
            req.add_header("X-Internal-Token", internal_token)
        urllib.request.urlopen(req, timeout=5)
        logger.info("API read-only connection released — waiting 3s for file lock release")
        _time.sleep(3)  # Wait for OS-level file locks to fully release
    except Exception as exc:
        logger.warning("Could not reset API connection: %s", exc)


def _copy_to_read_replica() -> None:
    """Copy the write DB to a read replica after pipeline completes.

    The API and agent tools read from the replica, so they never lock
    the write DB. Uses atomic rename to prevent partial reads.
    """
    try:
        tmp_path = DB_READ_PATH + ".tmp"
        shutil.copy2(DB_PATH, tmp_path)
        os.rename(tmp_path, DB_READ_PATH)  # atomic on Linux
        logger.info("Read replica updated: %s", DB_READ_PATH)
    except Exception as exc:
        logger.error("Failed to update read replica: %s", exc)


def _run_pipeline_chain() -> None:
    """Execute Silver -> Gold -> Embed chain.

    Opens a write-mode DuckDB connection, runs all three stages,
    closes the connection, then copies to read replica for the API.
    """
    success = False
    with _db_write_lock:
        con = _connect_with_retry(DB_PATH)
        try:
            con.execute("SET memory_limit = '512MB'")
            init_db(con)

            rows = silver.transform_all() or []
            inserted = silver.load(con, rows)
            logger.info("Silver: %d rows transformed, %d inserted", len(rows), inserted)

            # Silver detail
            detail_rows, headline_rows = silver.transform_all_detail()
            d_count, h_count = silver.load_detail(con, detail_rows, headline_rows)
            logger.info("Silver detail: %d detail, %d headlines", d_count, h_count)

            gold_rows = gold.aggregate(con)
            logger.info("Gold: %d rows inserted", gold_rows)

            embedded = embed_gold_scores(con)
            logger.info("Embed: %d documents upserted", embedded)
            success = True
        except Exception as exc:
            logger.error("Pipeline chain failed: %s", exc)
        finally:
            con.close()

    # Copy to read replica only on success — avoids serving inconsistent state
    if success:
        _copy_to_read_replica()
        _release_api_read_lock()  # Force API to reopen on the new replica
    else:
        logger.warning("Skipping read replica update due to pipeline failure")


# ---------------------------------------------------------------------------
# Scheduled jobs
# ---------------------------------------------------------------------------


def job_hourly_pipeline() -> None:
    """Hourly job: fetch fast sources, then run pipeline chain."""
    logger.info("=== Hourly pipeline: starting ===")
    _fetch_sources(FAST_SOURCES)
    _run_pipeline_chain()
    logger.info("=== Hourly pipeline: complete ===")


def job_daily_pipeline() -> None:
    """Daily 06:05 UTC job: fetch slow sources, then run pipeline chain."""
    logger.info("=== Daily pipeline: starting ===")
    _fetch_sources(SLOW_SOURCES)
    _run_pipeline_chain()
    logger.info("=== Daily pipeline: complete ===")


SILVER_RETENTION_DAYS = 90


def job_silver_retention() -> None:
    """Daily 03:00 UTC job: delete silver_metrics rows older than 90 days.

    Gold rows are kept forever (tiny footprint, needed for long-term trends).
    """
    logger.info("=== Silver retention: starting ===")
    with _db_write_lock:
        con = _connect_with_retry(DB_PATH)
        try:
            con.execute("SET memory_limit = '512MB'")
            result = con.execute(
                f"DELETE FROM silver_metrics "
                f"WHERE ingested_at < CURRENT_TIMESTAMP - INTERVAL {int(SILVER_RETENTION_DAYS)} DAY",
            )
            row = result.fetchone()
            count = row[0] if row else 0
            logger.info("Silver retention: deleted %d silver_metrics rows older than %d days", count, SILVER_RETENTION_DAYS)
            # Detail tables
            for table in ("silver_detail", "silver_headlines"):
                try:
                    r = con.execute(
                        f"DELETE FROM {table} "
                        f"WHERE ingested_at < CURRENT_TIMESTAMP - INTERVAL {int(SILVER_RETENTION_DAYS)} DAY",
                    )
                    c = r.fetchone()[0]
                    if c > 0:
                        logger.info("Silver retention: deleted %d %s rows", c, table)
                except Exception:
                    logger.debug("Silver retention: %s table may not exist yet", table)
        except Exception as exc:
            logger.error("Silver retention failed: %s", exc)
        finally:
            con.close()
    _copy_to_read_replica()
    logger.info("=== Silver retention: complete ===")


def job_daily_bulletin() -> None:
    """Daily 09:00 UTC job: generate the city health bulletin."""
    logger.info("=== Daily bulletin: starting ===")
    try:
        result = generate_bulletin(trigger="scheduled")
        if "error" in result:
            logger.error("Bulletin generation returned error: %s", result["error"])
        else:
            logger.info("Bulletin saved to %s", result.get("output_path"))
    except Exception as exc:
        logger.error("Bulletin generation failed: %s", exc)
    logger.info("=== Daily bulletin: complete ===")


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------


def _run_full_pipeline_once() -> None:
    """Run a single full pipeline cycle on startup (all sources).

    Ensures the database has data after the first ``docker compose up``.
    """
    logger.info("=== Startup pipeline: fetching all sources ===")
    all_sources = {**FAST_SOURCES, **SLOW_SOURCES}
    _fetch_sources(all_sources)
    _run_pipeline_chain()
    logger.info("=== Startup pipeline: complete ===")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Start the APScheduler daemon with all jobs configured."""
    ensure_bulletin_logs_table()

    scheduler = BlockingScheduler(timezone="UTC")

    # Hourly: fast sources + pipeline chain
    # max_instances=1 and coalesce=True prevent concurrent runs and collapse
    # missed firings into a single catch-up run.
    scheduler.add_job(
        job_hourly_pipeline,
        "cron",
        minute=0,
        misfire_grace_time=300,
        id="hourly_pipeline",
        max_instances=1,
        coalesce=True,
    )

    # Daily at 06:05 UTC: slow sources + pipeline chain
    # Offset to 06:05 to avoid a write-connection collision with the hourly
    # job that fires at 06:00.
    scheduler.add_job(
        job_daily_pipeline,
        "cron",
        hour=6,
        minute=5,
        misfire_grace_time=300,
        id="daily_pipeline",
        max_instances=1,
        coalesce=True,
    )

    # Daily at 03:00 UTC: silver retention cleanup (delete rows > 90 days)
    scheduler.add_job(
        job_silver_retention,
        "cron",
        hour=3,
        minute=0,
        misfire_grace_time=300,
        id="silver_retention",
        max_instances=1,
        coalesce=True,
    )

    # Daily at 09:30 UTC: bulletin generation (after 09:00 hourly pipeline finishes)
    scheduler.add_job(
        job_daily_bulletin,
        "cron",
        hour=9,
        minute=30,
        misfire_grace_time=300,
        id="daily_bulletin",
        max_instances=1,
        coalesce=True,
    )

    # Populate data on first launch as a non-blocking one-shot job so the
    # scheduler starts immediately rather than blocking main() for several minutes.
    scheduler.add_job(
        _run_full_pipeline_once,
        "date",
        id="startup_pipeline",
        misfire_grace_time=600,
    )

    # Graceful shutdown on SIGTERM (Docker stop)
    def _handle_sigterm(signum: int, frame: object) -> None:
        logger.info("Received SIGTERM — shutting down scheduler")
        scheduler.shutdown(wait=False)

    signal.signal(signal.SIGTERM, _handle_sigterm)

    logger.info(
        "Scheduler started — hourly pipeline, 03:00 silver retention, 06:05 slow pipeline, 09:30 bulletin"
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    main()
