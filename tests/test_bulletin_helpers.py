"""Unit tests for bulletin helper functions.

Covers _build_reliability_watch (red-flag + amber-concentration cases) and
_build_external_validity (paired-sample divergence with the
_EXTERNAL_VALIDITY_MIN_PAIRS guard). The MIN_PAIRS guard exists because
centred-residual divergence on a tiny sample produces a degenerate
within-set mean — the threshold is what keeps an unstable claim out of
the bulletin on partial-data days.

These tests stub `agents.bulletin.compare_boroughs` directly so the
helpers can be exercised without a live DuckDB connection.
"""

from __future__ import annotations

import pytest

from agents import bulletin


def _organs(flag_map: dict[str, str]) -> dict:
    return {"organs": {k: {"flag": v} for k, v in flag_map.items()}}


def test_reliability_watch_returns_none_when_score_quality_missing():
    assert bulletin._build_reliability_watch(None, [{"borough_code": "E09000007"}]) is None


def test_reliability_watch_returns_none_when_worst_empty():
    assert bulletin._build_reliability_watch({"E09000007": _organs({})}, []) is None


def test_reliability_watch_flags_red_organ_in_worst_borough():
    sq = {
        "E09000007": {
            "borough_name": "Camden",
            **_organs({"air_score": "red", "transit_score": "green", "immune_score": "green"}),
        }
    }
    worst = [{"borough_code": "E09000007"}]
    out = bulletin._build_reliability_watch(sq, worst)
    assert out is not None
    assert "Camden" in out
    assert "air" in out
    assert "Sparse underlying data" in out


def test_reliability_watch_combines_multiple_red_organs():
    sq = {
        "E09000007": {
            "borough_name": "Camden",
            **_organs({"air_score": "red", "transit_score": "red", "immune_score": "green"}),
        }
    }
    out = bulletin._build_reliability_watch(sq, [{"borough_code": "E09000007"}])
    assert "air" in out and "transit" in out


def test_reliability_watch_amber_concentration_when_two_amber_no_red():
    sq = {
        "E09000007": {
            "borough_name": "Camden",
            **_organs({"air_score": "amber", "transit_score": "amber", "immune_score": "green"}),
        }
    }
    out = bulletin._build_reliability_watch(sq, [{"borough_code": "E09000007"}])
    assert out is not None
    assert "Wide CIs across multiple organs" in out
    assert "Camden" in out


def test_reliability_watch_no_amber_concentration_with_only_one_amber():
    sq = {
        "E09000007": {
            "borough_name": "Camden",
            **_organs({"air_score": "amber", "transit_score": "green", "immune_score": "green"}),
        }
    }
    assert bulletin._build_reliability_watch(sq, [{"borough_code": "E09000007"}]) is None


def test_reliability_watch_red_takes_priority_over_amber_concentration():
    """A borough with red+amber+amber should appear in the red list, not the amber list."""
    sq = {
        "E09000007": {
            "borough_name": "Camden",
            **_organs({"air_score": "red", "transit_score": "amber", "immune_score": "amber"}),
        }
    }
    out = bulletin._build_reliability_watch(sq, [{"borough_code": "E09000007"}])
    assert out is not None
    assert "Sparse underlying data" in out
    # The amber-concentration sentence should NOT mention Camden, since
    # the borough is already in the red watch list.
    assert "Wide CIs across multiple organs in: Camden" not in out


def test_reliability_watch_skips_boroughs_missing_from_score_quality():
    sq = {}
    worst = [{"borough_code": "E09000007", "borough_name": "Camden"}]
    assert bulletin._build_reliability_watch(sq, worst) is None


def _patch_compare(monkeypatch, ranked: list[dict]) -> None:
    monkeypatch.setattr(
        bulletin,
        "compare_boroughs",
        lambda metric, top_n, ascending=False: {"boroughs": ranked},
    )


def test_external_validity_returns_none_without_health_index():
    assert bulletin._build_external_validity(None, {}, [], []) is None


def test_external_validity_returns_none_below_min_pairs(monkeypatch):
    """Sample of 5 paired boroughs should not produce a sentence."""
    ranked = [
        {"borough_code": f"E0900000{i}", "borough_name": f"B{i}", "score": 50 + i}
        for i in range(5)
    ]
    hi = {b["borough_code"]: {"name": b["borough_name"], "score": 100.0} for b in ranked}
    _patch_compare(monkeypatch, ranked)
    assert bulletin._build_external_validity(hi, {}, [], []) is None


def test_external_validity_returns_sentence_with_full_pair_set(monkeypatch):
    """32 paired boroughs with one large outlier should surface that outlier."""
    ranked = [
        {"borough_code": f"E090{i:05d}", "borough_name": f"B{i}", "score": 60.0}
        for i in range(32)
    ]
    # Outlier: CityScan high but HI low → centred residual large + positive
    ranked[0]["borough_name"] = "OutlierTown"
    ranked[0]["score"] = 90.0
    hi = {b["borough_code"]: {"name": b["borough_name"], "score": 100.0} for b in ranked}
    hi[ranked[0]["borough_code"]] = {"name": "OutlierTown", "score": 70.0}
    _patch_compare(monkeypatch, ranked)
    out = bulletin._build_external_validity(hi, {}, [], [])
    assert out is not None
    assert "32 paired boroughs" in out
    assert "OutlierTown" in out
    assert "CityScan reads relatively healthier" in out


def test_external_validity_skips_not_in_dataset_entries(monkeypatch):
    """City of London (not_in_dataset=True) should be excluded from the sample."""
    ranked = [
        {"borough_code": f"E090{i:05d}", "borough_name": f"B{i}", "score": 60.0}
        for i in range(25)
    ]
    hi = {b["borough_code"]: {"name": b["borough_name"], "score": 100.0} for b in ranked}
    # Mark one as excluded — shouldn't break, just trims the sample by 1.
    excluded_code = ranked[3]["borough_code"]
    hi[excluded_code] = {"not_in_dataset": True}
    _patch_compare(monkeypatch, ranked)
    out = bulletin._build_external_validity(hi, {}, [], [])
    assert out is not None
    assert "24 paired boroughs" in out


def test_external_validity_uses_score_year_fallback_keys(monkeypatch):
    """Static-shape entries lacking a 'score' key should fall through to score_<year>."""
    ranked = [
        {"borough_code": f"E090{i:05d}", "borough_name": f"B{i}", "score": 60.0}
        for i in range(22)
    ]
    hi = {
        b["borough_code"]: {"name": b["borough_name"], "score_2021": 100.0}
        for b in ranked
    }
    _patch_compare(monkeypatch, ranked)
    out = bulletin._build_external_validity(hi, {}, [], [])
    assert out is not None
    assert "22 paired boroughs" in out


def test_external_validity_negative_divergence_direction(monkeypatch):
    """An outlier where CityScan reads lower than HI should produce the
    'relatively worse' phrasing."""
    ranked = [
        {"borough_code": f"E090{i:05d}", "borough_name": f"B{i}", "score": 60.0}
        for i in range(32)
    ]
    ranked[0]["borough_name"] = "Underperformer"
    ranked[0]["score"] = 30.0
    hi = {b["borough_code"]: {"name": b["borough_name"], "score": 100.0} for b in ranked}
    _patch_compare(monkeypatch, ranked)
    out = bulletin._build_external_validity(hi, {}, [], [])
    assert "Underperformer" in out
    assert "CityScan reads relatively worse" in out
