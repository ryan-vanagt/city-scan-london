"""Test pipeline/bronze.py — save, cleanup, file existence."""

import json
from pathlib import Path

import pytest

from pipeline import bronze

# ---------------------------------------------------------------------------
# save() — creates file with correct content
# ---------------------------------------------------------------------------

def test_save_returns_a_path(tmp_path, monkeypatch):
    monkeypatch.setattr(bronze, "BRONZE_BASE", tmp_path)
    path_str = bronze.save("_test_sandbox", {"test": True, "values": [1, 2, 3]})
    assert path_str is not None


def test_save_file_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(bronze, "BRONZE_BASE", tmp_path)
    path_str = bronze.save("_test_sandbox", {"test": True, "values": [1, 2, 3]})
    assert Path(path_str).exists()


def test_save_content_matches_input(tmp_path, monkeypatch):
    monkeypatch.setattr(bronze, "BRONZE_BASE", tmp_path)
    test_data = {"test": True, "values": [1, 2, 3]}
    path_str = bronze.save("_test_sandbox", test_data)
    with open(path_str) as f:
        loaded = json.load(f)
    assert loaded == test_data


# ---------------------------------------------------------------------------
# save() — handles list data
# ---------------------------------------------------------------------------

def test_save_handles_list_data(tmp_path, monkeypatch):
    monkeypatch.setattr(bronze, "BRONZE_BASE", tmp_path)
    list_data = [{"a": 1}, {"b": 2}]
    path_str = bronze.save("_test_sandbox_list", list_data)
    assert Path(path_str).exists()


def test_save_list_content_matches(tmp_path, monkeypatch):
    monkeypatch.setattr(bronze, "BRONZE_BASE", tmp_path)
    list_data = [{"a": 1}, {"b": 2}]
    path_str = bronze.save("_test_sandbox_list", list_data)
    with open(path_str) as f:
        loaded = json.load(f)
    assert loaded == list_data


# ---------------------------------------------------------------------------
# Bronze dirs have data for all 7 sources
# ---------------------------------------------------------------------------

EXPECTED_SOURCES = ["openaq", "tfl", "guardian", "bbc", "reddit", "met_police", "nhs_ae"]


@pytest.mark.parametrize("source", EXPECTED_SOURCES)
def test_bronze_source_dir_has_data(source):
    source_dir = bronze.BRONZE_BASE / source
    if not source_dir.exists():
        pytest.skip(f"bronze/{source}/ does not exist — run pipeline first")
    files = sorted(source_dir.glob("*.json"))
    assert len(files) > 0, f"bronze/{source}/ has no JSON files"


# ---------------------------------------------------------------------------
# cleanup() — keeps recent, deletes old
# ---------------------------------------------------------------------------

def test_cleanup_days_zero_deletes_all(tmp_path, monkeypatch):
    monkeypatch.setattr(bronze, "BRONZE_BASE", tmp_path)

    # Create two files under a test source directory
    bronze.save("_test_cleanup", {"file": "first"})
    second_path = tmp_path / "_test_cleanup" / "extra_file.json"
    second_path.parent.mkdir(parents=True, exist_ok=True)
    second_path.write_text(json.dumps({"file": "second"}), encoding="utf-8")

    cleanup_dir = tmp_path / "_test_cleanup"
    files_before = list(cleanup_dir.glob("*.json"))
    assert len(files_before) >= 2, f"expected >= 2 files before cleanup, got {len(files_before)}"

    bronze.cleanup("_test_cleanup", days=0)

    files_after = list(cleanup_dir.glob("*.json"))
    assert len(files_after) == 0, f"expected 0 files after cleanup(days=0), got {len(files_after)}"
