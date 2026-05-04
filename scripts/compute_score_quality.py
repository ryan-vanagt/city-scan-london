"""
Compute per-borough × per-organ data-quality flags + bootstrapped composite CIs.

Output: data/static/score_quality.json — a static lookup the API serves and
the frontend renders as small green/amber/red dots next to each score.

Per-organ flag derivation:
  - air_score, transit_score, immune_score, composite_score: bootstrap the
    mean of the borough's recent gold time-series (default 30 days). Quality
    flag derived from the 95% CI width.
  - sentiment_score: structurally London-wide → flagged amber with disclosure.
  - green_space_score / green_space_access_score: static annual GLA snapshot →
    flagged amber with disclosure.
  - air_quality_modelled_score: static LAEI baseline → flagged amber.
  - Boroughs with a NULL latest reading get flagged red.

Reads from the live API (default https://cityscanldn.app/api). Override
with CITYSCAN_API_URL. The script is idempotent — re-run when the gold
layer refreshes; output overwrites the static JSON.

Usage:
  python -m scripts.compute_score_quality
  CITYSCAN_API_URL=http://localhost:8000 python -m scripts.compute_score_quality
"""

from __future__ import annotations

import json
import logging
import os
import random
import statistics
import sys
from pathlib import Path
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import certifi

_SSL_CTX = ssl.create_default_context(cafile=certifi.where())

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "https://cityscanldn.app/api"
TREND_DAYS = 30
BOOTSTRAP_N = 1000

# Organs that get a real bootstrap-derived flag.
BOOTSTRAPPABLE_ORGANS = (
    "air_score",
    "transit_score",
    "immune_score",
    "composite_score",
)

# Organs whose underlying signal is precise but slow-cadence or wide-scope.
# Bootstrap is uninformative (constant time-series → zero variance), but
# the SCORE is reliable for what it measures — green space coverage is
# precisely measured by GIS even if the data refreshes annually, and
# LAEI is a sophisticated atmospheric model. We flag these GREEN
# (reliable) with a disclosure note carrying the cadence / scope caveat.
STATIC_GREEN_NOTES: dict[str, str] = {
    "sentiment_score": (
        "London-wide signal — same value across all boroughs. "
        "Score reliable; not borough-specific."
    ),
    "green_space_score": (
        "GLA 2024 green-cover measurement — precise; updated yearly because "
        "physical coverage doesn't change daily."
    ),
    "green_space_access_score": (
        "GLA 2024 (population-weighted) — precise; yearly update cycle."
    ),
    "air_quality_modelled_score": (
        "LAEI 2022 atmospheric model — precise for the year modelled; "
        "annual update."
    ),
}

# CI-width thresholds (in composite score points).
GREEN_THRESHOLD = 5.0
AMBER_THRESHOLD = 15.0

# Minimum number of non-null observations required to bootstrap.
MIN_OBS = 10

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = REPO_ROOT / "data" / "static" / "score_quality.json"


def _api_get(url: str) -> dict:
    with urlopen(url, timeout=30, context=_SSL_CTX) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _bootstrap_mean_ci(values: list[float], n: int = BOOTSTRAP_N) -> tuple[float, float, float]:
    """Bootstrap the mean. Returns (ci_low, ci_high, width) at 95%.

    Uses non-parametric resampling with replacement.
    """
    rng = random.Random(0xC17C5CA4)  # deterministic — same data → same CI
    k = len(values)
    means: list[float] = []
    for _ in range(n):
        sample = [values[rng.randrange(k)] for _ in range(k)]
        means.append(sum(sample) / k)
    means.sort()
    lo = means[int(0.025 * n)]
    hi = means[int(0.975 * n)]
    return lo, hi, hi - lo


def _flag_from_width(width: float) -> str:
    if width < GREEN_THRESHOLD:
        return "green"
    if width < AMBER_THRESHOLD:
        return "amber"
    return "red"


def _process_borough(api_url: str, borough: dict) -> dict:
    """Fetch trend + compute quality for one borough across all organs."""
    code = borough["borough_code"]
    name = borough["borough_name"]
    trend_url = f"{api_url}/borough/{code}/trend?days={TREND_DAYS}"
    try:
        trend = _api_get(trend_url)
    except (HTTPError, URLError) as exc:
        logger.warning("Trend fetch failed for %s: %s", name, exc)
        return {"borough_code": code, "borough_name": name, "organs": {}}

    rows = trend.get("trend", [])

    organs_out: dict[str, dict] = {}
    for organ_key in (
        "air_score",
        "air_quality_modelled_score",
        "transit_score",
        "sentiment_score",
        "immune_score",
        "green_space_score",
        "green_space_access_score",
        "composite_score",
    ):
        values = [r[organ_key] for r in rows if r.get(organ_key) is not None]
        latest_value = borough.get(organ_key)

        # Static-disclosure organs: precise signal but slow-cadence or
        # wide-scope. Score is reliable; the disclosure note carries
        # the cadence/scope caveat for the analyst.
        if organ_key in STATIC_GREEN_NOTES:
            organs_out[organ_key] = {
                "flag": "green",
                "ci_low": None,
                "ci_high": None,
                "width": None,
                "n": len(values),
                "note": STATIC_GREEN_NOTES[organ_key],
            }
            continue

        # Latest is NULL — usually a sparse-sensor borough (air_score).
        if latest_value is None:
            organs_out[organ_key] = {
                "flag": "red",
                "ci_low": None,
                "ci_high": None,
                "width": None,
                "n": 0,
                "note": "No recent reading — local sensor coverage gap.",
            }
            continue

        # Insufficient observations to bootstrap.
        if len(values) < MIN_OBS:
            organs_out[organ_key] = {
                "flag": "red",
                "ci_low": None,
                "ci_high": None,
                "width": None,
                "n": len(values),
                "note": f"Only {len(values)} recent observations — too few for stable CI.",
            }
            continue

        # Bootstrap the mean.
        lo, hi, width = _bootstrap_mean_ci(values)
        flag = _flag_from_width(width)
        sd = statistics.stdev(values) if len(values) > 1 else 0.0
        organs_out[organ_key] = {
            "flag": flag,
            "ci_low": round(lo, 2),
            "ci_high": round(hi, 2),
            "width": round(width, 2),
            "sd": round(sd, 2),
            "n": len(values),
        }

    # The composite is averaged from the 5 organs, so bootstrapping it
    # always yields a narrow CI even when an underlying organ is sparse.
    # Override the composite flag with one derived from the bootstrappable
    # input organs (air_score, transit_score, immune_score) — that captures
    # actual input completeness rather than just temporal smoothness.
    if "composite_score" in organs_out:
        core_flags = [
            organs_out["air_score"]["flag"],
            organs_out["transit_score"]["flag"],
            organs_out["immune_score"]["flag"],
        ]
        red = core_flags.count("red")
        amber = core_flags.count("amber")
        if red >= 2:
            composite_flag = "red"
        elif red == 1 or amber >= 2:
            composite_flag = "amber"
        else:
            composite_flag = "green"
        organs_out["composite_score"]["flag"] = composite_flag
        organs_out["composite_score"]["flag_basis"] = (
            f"derived from input organs: {red} red, {amber} amber, "
            f"{3 - red - amber} green of 3 bootstrappable inputs"
        )

    return {
        "borough_code": code,
        "borough_name": name,
        "organs": organs_out,
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    api_url = os.environ.get("CITYSCAN_API_URL", DEFAULT_API_URL).rstrip("/")
    logger.info("Computing score quality from %s", api_url)

    boroughs = _api_get(f"{api_url}/boroughs")
    logger.info("Loaded %d boroughs", len(boroughs))

    results = []
    for b in boroughs:
        results.append(_process_borough(api_url, b))

    payload = {
        "_metadata": {
            "method": (
                "Per-organ score reliability from bootstrap-of-mean CI on the "
                f"borough's last {TREND_DAYS} days of gold time-series. "
                "Static-cadence signals (sentiment, green-space variants, "
                "modelled air) are flagged green with a disclosure note about "
                "their cadence or scope — the score is precise, the bootstrap "
                "is just uninformative on a constant time-series."
            ),
            "bootstrap_resamples": BOOTSTRAP_N,
            "trend_window_days": TREND_DAYS,
            "thresholds": {
                "green_ci_width_lt": GREEN_THRESHOLD,
                "amber_ci_width_lt": AMBER_THRESHOLD,
            },
            "min_observations_for_ci": MIN_OBS,
            "n_boroughs": len(results),
        },
        "boroughs": {r["borough_code"]: r for r in results},
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("Wrote %s (%d boroughs)", OUTPUT_PATH, len(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
