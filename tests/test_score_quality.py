"""Tests for the score-quality static dataset."""

import json
from pathlib import Path

import pytest

DATA_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "static" / "score_quality.json"
)

EXPECTED_CODES = {f"E0900{str(i).zfill(4)}" for i in range(1, 34)}

EXPECTED_ORGANS = {
    "air_score",
    "air_quality_modelled_score",
    "transit_score",
    "sentiment_score",
    "immune_score",
    "green_space_score",
    "green_space_access_score",
    "composite_score",
}

VALID_FLAGS = {"green", "amber", "red"}


@pytest.fixture(scope="module")
def quality_data() -> dict:
    if not DATA_PATH.exists():
        pytest.skip(
            "Score quality data not generated — run "
            "scripts/compute_score_quality.py first"
        )
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_metadata_present(quality_data: dict) -> None:
    meta = quality_data.get("_metadata", {})
    assert "method" in meta
    assert "thresholds" in meta
    assert isinstance(meta["bootstrap_resamples"], int)
    assert meta["bootstrap_resamples"] >= 100


def test_all_33_boroughs(quality_data: dict) -> None:
    boroughs = quality_data["boroughs"]
    assert len(boroughs) == 33


def test_all_expected_codes_present(quality_data: dict) -> None:
    found = set(quality_data["boroughs"].keys())
    missing = EXPECTED_CODES - found
    assert not missing


def test_each_borough_has_all_organs(quality_data: dict) -> None:
    for code, b in quality_data["boroughs"].items():
        organs = set(b["organs"].keys())
        missing = EXPECTED_ORGANS - organs
        assert not missing, f"{b['borough_name']} missing organs: {missing}"


def test_all_flags_valid(quality_data: dict) -> None:
    for code, b in quality_data["boroughs"].items():
        for organ, q in b["organs"].items():
            assert q["flag"] in VALID_FLAGS, (
                f"{b['borough_name']} {organ} flag '{q['flag']}' invalid"
            )


def test_borough_specific_static_organs_are_green(quality_data: dict) -> None:
    """Modelled air and green-space variants give a real per-borough value
    (LAEI runs per LA, GLA cover is per LA). Slow cadence doesn't reduce
    reliability — flagged green with a cadence note."""
    borough_specific_static = {
        "air_quality_modelled_score",
        "green_space_score",
        "green_space_access_score",
    }
    for code, b in quality_data["boroughs"].items():
        for organ in borough_specific_static:
            q = b["organs"][organ]
            assert q["flag"] == "green", (
                f"{b['borough_name']} {organ} should be green, got {q['flag']}"
            )
            assert q.get("note"), (
                f"{b['borough_name']} {organ} green but no disclosure note"
            )


def test_sentiment_is_amber_borough_scope(quality_data: dict) -> None:
    """Sentiment is a London-wide signal applied uniformly to every borough.
    The number is reliable for London but is not a per-borough reading —
    borough-level use deserves an amber 'use with care' flag with a scope
    disclosure."""
    for code, b in quality_data["boroughs"].items():
        q = b["organs"]["sentiment_score"]
        assert q["flag"] == "amber", (
            f"{b['borough_name']} sentiment should be amber (not borough-specific), "
            f"got {q['flag']}"
        )
        assert q.get("note"), f"{b['borough_name']} sentiment amber but no note"


def test_bootstrap_ci_present_for_bootstrappable_green_organs(quality_data: dict) -> None:
    """When a bootstrappable organ has a green flag, the CI fields should be
    populated. Static-cadence organs (sentiment, modelled air, green-space
    variants) are also flagged green but legitimately don't carry a CI —
    they have a disclosure note instead."""
    static_organs = {
        "sentiment_score",
        "air_quality_modelled_score",
        "green_space_score",
        "green_space_access_score",
    }
    for code, b in quality_data["boroughs"].items():
        for organ, q in b["organs"].items():
            if organ in static_organs or organ == "composite_score":
                continue
            if q["flag"] == "green":
                assert q["ci_low"] is not None, (
                    f"{b['borough_name']} {organ} green but no CI"
                )
                assert q["ci_high"] is not None
                assert q["width"] is not None
                assert q["ci_low"] <= q["ci_high"]


def test_composite_flag_derived_from_inputs(quality_data: dict) -> None:
    """Composite flag should reflect input organ quality, not its own bootstrap."""
    for code, b in quality_data["boroughs"].items():
        c = b["organs"]["composite_score"]
        assert "flag_basis" in c, (
            f"{b['borough_name']} composite missing flag_basis explanation"
        )


def test_loader_function() -> None:
    if not DATA_PATH.exists():
        pytest.skip("Score quality data not generated")
    try:
        from api.routers.boroughs import _load_score_quality_data
    except ModuleNotFoundError as exc:
        pytest.skip(f"API deps not installed locally ({exc.name}); run on server / in CI")
    _load_score_quality_data.cache_clear()
    payload = _load_score_quality_data()
    assert "boroughs" in payload
    assert "_metadata" in payload
    assert len(payload["boroughs"]) == 33
