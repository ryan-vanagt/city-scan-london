"""
Bronze layer writer.

Saves raw API responses as timestamped JSON files under /data/bronze/{source}/.
No transformation is applied at this stage — data is stored exactly as received.
Also provides a rolling retention cleanup to keep disk usage bounded.
"""

import json
import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

BRONZE_BASE = Path(__file__).resolve().parent.parent / "data" / "bronze"


def save(source: str, data: dict | list) -> str:
    """Write raw API response to a timestamped JSON file in the bronze layer.

    Args:
        source: Source name (e.g. "openaq", "tfl"). Determines subdirectory.
        data: Raw API response (dict or list) to persist.

    Returns:
        Path to the written file as a string.
    """
    # Validate source name to prevent path traversal
    if "/" in source or "\\" in source or ".." in source:
        raise ValueError(f"Invalid source name: {source!r}")

    directory = BRONZE_BASE / source
    directory.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    file_path = directory / f"{timestamp}.json"

    # Atomic write: write to temp file then rename, so silver never reads a partial file
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".json.tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp_path, file_path)
    except (OSError, TypeError) as exc:
        logger.error("Bronze save failed for %s: %s", file_path, exc)
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    logger.info("Bronze save: %s", file_path)
    return str(file_path)


def cleanup(source: str, days: int = 7) -> None:
    """Delete bronze files older than `days` days for the given source.

    Args:
        source: Source name (e.g. "openaq"). Determines subdirectory.
        days: Files older than this many days are deleted. Defaults to 7.
    """
    directory = BRONZE_BASE / source
    if not directory.exists():
        return

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    for file_path in directory.glob("*.json"):
        mtime = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc)
        if mtime < cutoff:
            file_path.unlink()
            logger.info("Bronze cleanup: deleted %s", file_path)
