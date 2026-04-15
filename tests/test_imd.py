"""Tests for IMD deprivation data integrity."""

import json
from pathlib import Path

import pytest

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "static" / "imd_borough.json"

EXPECTED_CODES = {f"E0900{str(i).zfill(4)}" for i in range(1, 34)}
EXPECTED_DOMAINS = {"income", "employment", "education", "health", "crime", "barriers", "living"}


@pytest.fixture(scope="module")
def imd_data() -> dict:
    """Load IMD data, skip if file not generated yet."""
    if not DATA_PATH.exists():
        pytest.skip("IMD data not generated — run scripts/fetch_imd.py first")
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_all_33_boroughs(imd_data: dict) -> None:
    boroughs = imd_data["boroughs"]
    assert len(boroughs) == 33, f"Expected 33 boroughs, got {len(boroughs)}"


def test_all_expected_codes_present(imd_data: dict) -> None:
    found = set(imd_data["boroughs"].keys())
    missing = EXPECTED_CODES - found
    assert not missing, f"Missing borough codes: {missing}"


def test_imd_ranks_in_valid_range(imd_data: dict) -> None:
    for code, b in imd_data["boroughs"].items():
        rank = b["imd_rank"]
        assert 1 <= rank <= 296, f"{b['name']} rank {rank} out of range 1-296"


def test_no_duplicate_ranks(imd_data: dict) -> None:
    ranks = [b["imd_rank"] for b in imd_data["boroughs"].values()]
    assert len(ranks) == len(set(ranks)), "Duplicate IMD ranks found"


def test_imd_scores_positive(imd_data: dict) -> None:
    for code, b in imd_data["boroughs"].items():
        assert b["imd_score"] > 0, f"{b['name']} score {b['imd_score']} not positive"


def test_pct_most_deprived_in_range(imd_data: dict) -> None:
    for code, b in imd_data["boroughs"].items():
        pct = b["pct_most_deprived_10"]
        assert 0 <= pct <= 100, f"{b['name']} pct {pct} out of range 0-100"


def test_all_7_domains_present(imd_data: dict) -> None:
    for code, b in imd_data["boroughs"].items():
        domains = set(b.get("domains", {}).keys())
        missing = EXPECTED_DOMAINS - domains
        assert not missing, f"{b['name']} missing domains: {missing}"


def test_domain_ranks_in_valid_range(imd_data: dict) -> None:
    for code, b in imd_data["boroughs"].items():
        for domain, vals in b.get("domains", {}).items():
            rank = vals["rank"]
            assert 1 <= rank <= 296, (
                f"{b['name']} {domain} rank {rank} out of range 1-296"
            )


def test_most_deprived_is_newham(imd_data: dict) -> None:
    """Cross-check: Newham should be the most deprived London borough (IMD 2025)."""
    most = min(imd_data["boroughs"].values(), key=lambda b: b["imd_rank"])
    assert most["name"] == "Newham", (
        f"Expected Newham as most deprived, got {most['name']} (rank {most['imd_rank']})"
    )


def test_metadata_present(imd_data: dict) -> None:
    meta = imd_data.get("_metadata", {})
    assert "source" in meta
    assert "2025" in meta.get("published", "")
    assert meta.get("total_lads") == 296
