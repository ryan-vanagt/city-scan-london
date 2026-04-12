"""Test ingestion/scheduler.py — source groups, fetch/chain helpers, error handling.

Tests the scheduler's internal functions without starting APScheduler or
hitting real external APIs. Uses mock source modules and in-memory DuckDB.
"""

import json
import logging
from pathlib import Path
from types import ModuleType

import pytest

from ingestion.scheduler import (
    FAST_SOURCES,
    SLOW_SOURCES,
    _fetch_sources,
)

logging.basicConfig(level=logging.WARNING)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Source group definitions
# ---------------------------------------------------------------------------

def test_fast_sources_has_5_entries():
    assert len(FAST_SOURCES) == 5, f"got {len(FAST_SOURCES)}"


def test_slow_sources_has_2_entries():
    assert len(SLOW_SOURCES) == 2, f"got {len(SLOW_SOURCES)}"


def test_fast_sources_keys_correct():
    expected_fast = {"openaq", "tfl", "guardian", "bbc", "reddit"}
    assert set(FAST_SOURCES.keys()) == expected_fast, f"got {set(FAST_SOURCES.keys())}"


def test_slow_sources_keys_correct():
    expected_slow = {"met_police", "nhs_ae"}
    assert set(SLOW_SOURCES.keys()) == expected_slow, f"got {set(SLOW_SOURCES.keys())}"


def test_no_overlap_between_fast_and_slow():
    overlap = set(FAST_SOURCES.keys()) & set(SLOW_SOURCES.keys())
    assert len(overlap) == 0, f"overlap: {overlap}"


@pytest.mark.parametrize("name,mod", list({**FAST_SOURCES, **SLOW_SOURCES}.items()))
def test_each_source_is_a_module(name, mod):
    assert isinstance(mod, ModuleType), f"{name} is not a ModuleType"


@pytest.mark.parametrize("name,mod", list({**FAST_SOURCES, **SLOW_SOURCES}.items()))
def test_each_source_has_fetch_callable(name, mod):
    assert hasattr(mod, "fetch") and callable(mod.fetch), \
        f"{name} missing callable fetch()"


# ---------------------------------------------------------------------------
# _fetch_sources — successful source
# ---------------------------------------------------------------------------

def test_fetch_sources_creates_bronze_file(tmp_path, monkeypatch):
    import pipeline.bronze as bronze_module
    monkeypatch.setattr(bronze_module, "BRONZE_BASE", tmp_path)

    mock_good = ModuleType("mock_good")
    mock_good.fetch = lambda: {"items": [{"id": 1}], "fetched_at": "2026-04-12T00:00:00Z"}

    _fetch_sources({"mock_good": mock_good})

    bronze_dir = tmp_path / "mock_good"
    bronze_files = list(bronze_dir.glob("*.json")) if bronze_dir.exists() else []
    assert len(bronze_files) >= 1, f"expected >= 1 bronze file, found {len(bronze_files)}"


# ---------------------------------------------------------------------------
# _fetch_sources — failing source
# ---------------------------------------------------------------------------

def test_fetch_sources_does_not_crash_on_failing_source():
    mock_bad = ModuleType("mock_bad")
    mock_bad.fetch = lambda: (_ for _ in ()).throw(RuntimeError("API unreachable"))

    # Should not raise — failures are logged and skipped
    _fetch_sources({"mock_bad": mock_bad})


# ---------------------------------------------------------------------------
# _fetch_sources — mixed (one good, one bad)
# ---------------------------------------------------------------------------

def test_fetch_sources_bad_skipped_good_saved(tmp_path, monkeypatch):
    import pipeline.bronze as bronze_module
    monkeypatch.setattr(bronze_module, "BRONZE_BASE", tmp_path)

    mock_good_2 = ModuleType("mock_good_2")
    mock_good_2.fetch = lambda: {"items": [], "fetched_at": "2026-04-12T00:00:00Z"}

    mock_bad_2 = ModuleType("mock_bad_2")
    mock_bad_2.fetch = lambda: (_ for _ in ()).throw(ConnectionError("timeout"))

    _fetch_sources({"mock_bad_2": mock_bad_2, "mock_good_2": mock_good_2})

    bronze_dir_2 = tmp_path / "mock_good_2"
    bronze_files_2 = list(bronze_dir_2.glob("*.json")) if bronze_dir_2.exists() else []
    assert len(bronze_files_2) >= 1, \
        f"good source should have produced a bronze file, found {len(bronze_files_2)}"


# ---------------------------------------------------------------------------
# _run_pipeline_chain — conditional on real bronze data
# ---------------------------------------------------------------------------

def _has_bronze_data() -> bool:
    bronze_root = _PROJECT_ROOT / "data" / "bronze"
    if not bronze_root.exists():
        return False
    return any(
        f.suffix == ".json"
        for d in bronze_root.iterdir() if d.is_dir()
        for f in d.iterdir()
    )


def test_pipeline_chain_completes_with_bronze_data():
    if not _has_bronze_data():
        pytest.skip("no bronze data on disk — run pipeline first")

    from ingestion.scheduler import _run_pipeline_chain
    _run_pipeline_chain()  # should not raise


# ---------------------------------------------------------------------------
# Job function imports
# ---------------------------------------------------------------------------

def test_job_hourly_pipeline_is_callable():
    from ingestion.scheduler import job_hourly_pipeline
    assert callable(job_hourly_pipeline)


def test_job_daily_pipeline_is_callable():
    from ingestion.scheduler import job_daily_pipeline
    assert callable(job_daily_pipeline)


def test_job_daily_bulletin_is_callable():
    from ingestion.scheduler import job_daily_bulletin
    assert callable(job_daily_bulletin)


def test_run_full_pipeline_once_is_callable():
    from ingestion.scheduler import _run_full_pipeline_once
    assert callable(_run_full_pipeline_once)


def test_main_is_callable():
    from ingestion.scheduler import main
    assert callable(main)
