"""
Compute per-borough × per-organ data-quality flags + bootstrapped composite CIs.

Output: data/static/score_quality.json — a static lookup the API serves and
the frontend renders as small green/amber/red dots next to each score.

Per-organ flag derivation (four paths):
  - air_score, transit_score, immune_score: bootstrap the mean of the
    borough's recent gold time-series (default 30 days). Flag derived from
    the 95% CI width (green <5 pts, amber <15, red ≥15 or null reading).
  - green_space_score / green_space_access_score / air_quality_modelled_score:
    borough-specific signals on slow (annual) cadence. Flagged GREEN with a
    cadence note — the score is precise for its vintage; bootstrap is
    uninformative on a constant time-series.
  - sentiment_score: London-wide news signal applied uniformly to every
    borough. Flagged AMBER with a scope note — score is reliable in
    absolute terms but is not a per-borough reading.
  - composite_score: bootstrap is run for the CI numbers, but the FLAG is
    overridden based on the count of red/amber input organs (red if 2+ red,
    amber if 1 red OR 2+ amber, else green). When overridden to amber/red,
    the bootstrap CI is nulled out so the tooltip doesn't render a
    contradictory "stable" message alongside a low-quality flag.

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

# Organs whose underlying signal is precise AND borough-specific but slow
# cadence (annual refresh). Bootstrap is uninformative on a constant
# time-series, but each borough has a real, distinct, accurate value —
# flagged GREEN with a disclosure note about the update cadence.
STATIC_GREEN_NOTES: dict[str, str] = {
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

# Organs whose value is NOT borough-specific — applied uniformly across
# all 33 boroughs (sentiment is a London-wide news signal). The score is
# reliable for what it measures (London), but borough-level use deserves
# a "use with care" amber flag because it isn't actually a per-borough
# reading.
STATIC_AMBER_NOTES: dict[str, str] = {
    "sentiment_score": (
        "London-wide news signal — same value applied to every borough. "
        "Reliable for London, not borough-specific."
    ),
}

# CI-width thresholds (in composite score points).
GREEN_THRESHOLD = 5.0
AMBER_THRESHOLD = 15.0

# Minimum number of non-null observations required to bootstrap.
MIN_OBS = 10

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = REPO_ROOT / "data" / "static" / "score_quality.json"

# CITYSCAN_API_URL is the only knob we accept for the API base; if anyone
# ever points the script at a third-party host (intentionally or via a typo)
# we want the request to fail-closed rather than silently exfiltrate the
# borough trend payload to an arbitrary URL. The allowlist matches the
# default + the loopback URLs developers actually use.
_API_HOST_ALLOWLIST = (
    "cityscanldn.app",
    "localhost",
    "127.0.0.1",
)


def _api_get(url: str) -> dict:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Refusing non-http(s) URL: {url}")
    host = (parsed.hostname or "").lower()
    if host not in _API_HOST_ALLOWLIST:
        raise ValueError(
            f"Refusing API URL with non-allowlisted host: {host!r}. "
            f"Set CITYSCAN_API_URL to one of: {', '.join(_API_HOST_ALLOWLIST)}"
        )
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


def _derive_composite_flag(
    air_flag: str, transit_flag: str, immune_flag: str
) -> tuple[str, str]:
    """Derive composite_score flag from the three bootstrappable input
    organs.

    The composite is averaged from five organs, so bootstrapping it
    yields a narrow CI even when an underlying organ is sparse. We
    override that flag with one based on the input organs' flags so the
    surfaced quality reflects actual input completeness rather than
    temporal smoothness.

    Rules:
        - red    if 2 or more inputs are red
        - amber  if exactly 1 input is red, OR 2 or more are amber
        - green  otherwise

    Returns (flag, basis_string).
    """
    flags = (air_flag, transit_flag, immune_flag)
    red = flags.count("red")
    amber = flags.count("amber")
    if red >= 2:
        flag = "red"
    elif red == 1 or amber >= 2:
        flag = "amber"
    else:
        flag = "green"
    basis = (
        f"derived from input organs: {red} red, {amber} amber, "
        f"{3 - red - amber} green of 3 bootstrappable inputs"
    )
    return flag, basis


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

        # Static-disclosure organs (borough-specific but slow cadence) →
        # green flag with cadence note.
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

        # Non-borough-specific signals (e.g. sentiment is London-wide) →
        # amber flag because borough-level use deserves "use with care".
        if organ_key in STATIC_AMBER_NOTES:
            organs_out[organ_key] = {
                "flag": "amber",
                "ci_low": None,
                "ci_high": None,
                "width": None,
                "n": len(values),
                "note": STATIC_AMBER_NOTES[organ_key],
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
        composite_flag, basis = _derive_composite_flag(
            organs_out["air_score"]["flag"],
            organs_out["transit_score"]["flag"],
            organs_out["immune_score"]["flag"],
        )
        organs_out["composite_score"]["flag"] = composite_flag
        organs_out["composite_score"]["flag_basis"] = basis
        # When overridden to amber/red, suppress the composite bootstrap CI —
        # the composite mean's narrow CI contradicts the input-quality flag
        # and reads as "stable but unreliable" in the tooltip.
        if composite_flag != "green":
            organs_out["composite_score"]["ci_low"] = None
            organs_out["composite_score"]["ci_high"] = None
            organs_out["composite_score"]["width"] = None

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
                "Per-organ score quality from bootstrap-of-mean CI on the "
                f"borough's last {TREND_DAYS} days of gold time-series for "
                "bootstrappable organs (air, transit, immune). Borough-"
                "specific static signals (green-space variants, modelled "
                "air) are flagged green with a cadence note. London-wide "
                "signals (sentiment) are flagged amber because they are not "
                "borough-specific. Composite_score flag is derived from the "
                "input organ flags (red if 2+ red, amber if 1 red OR 2+ "
                "amber, else green); its bootstrap CI is nulled when "
                "overridden to avoid contradicting the input-quality flag."
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
