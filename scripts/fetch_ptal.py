"""
Fetch TfL Public Transport Accessibility Levels (PTAL) at borough level.

PTAL is the official accessibility metric used by the GLA, TfL, and the
Cabinet Office to describe how well-served by public transport a given
area is. The score combines walk-time-to-stop, service frequency, and
mode availability. Bands run 1a (very poor) → 6b (excellent).

This script pulls the borough-level pre-aggregated CSV from
data.london.gov.uk (TfL's open data portal). No LSOA-to-borough join
needed — TfL publishes the borough average directly.

Vintage note: the most recent PTAL borough release on data.london.gov.uk
is from 2015 (`AvPTAI2015`). PTAL is structural — it captures network
geography that does not change radically year-on-year — but the figure
is honestly disclosed as 2015 in metadata and surfaced in the API.

Output: data/static/transit_access.json. Score normalisation:
    score_0_to_100 = min-max(log(1 + avptai_2015))
The log transform compresses the City of London outlier (~90 raw, ~3x
the next borough); without it, every other borough would render as
near-zero on the 0-100 scale. Same approach used for crime per-capita
elsewhere in the pipeline.

Usage:
    python -m scripts.fetch_ptal
"""

from __future__ import annotations

import csv
import json
import logging
import math
import ssl
import sys
from io import StringIO
from pathlib import Path
from urllib.request import Request, urlopen

import certifi

_SSL_CTX = ssl.create_default_context(cafile=certifi.where())

logger = logging.getLogger(__name__)

PTAL_CSV_URL = (
    "https://data.london.gov.uk/download/24rz6/"
    "8e520b81-dd06-4ce6-aaa0-972dccf84b57/Borough%20AvPTAI2015.csv"
)
PTAL_VINTAGE = 2015

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = REPO_ROOT / "data" / "static" / "transit_access.json"


def _download() -> str:
    logger.info("Downloading %s", PTAL_CSV_URL)
    req = Request(PTAL_CSV_URL, headers={"User-Agent": "cityscan/1.0"})
    with urlopen(req, timeout=30, context=_SSL_CTX) as resp:
        return resp.read().decode("utf-8")


def _parse_csv(text: str) -> list[dict]:
    rows = list(csv.DictReader(StringIO(text)))
    out = []
    for r in rows:
        code = r.get("Borough Code", "").strip()
        name = r.get("Borough Name", "").strip()
        try:
            avptai = float(r.get("AvPTAI2015", "").strip())
        except (ValueError, TypeError):
            continue
        band = r.get("PTAL", "").strip()
        out.append({"code": code, "name": name, "avptai_2015": avptai, "ptal_band": band})
    return out


def _normalise(rows: list[dict]) -> list[dict]:
    """Compute 0-100 score from log(1 + AvPTAI2015), min-max across boroughs."""
    if not rows:
        return rows
    log_vals = [math.log1p(r["avptai_2015"]) for r in rows]
    lo, hi = min(log_vals), max(log_vals)
    span = hi - lo if hi > lo else 1.0
    for r, lv in zip(rows, log_vals):
        r["score_0_to_100"] = round(((lv - lo) / span) * 100.0, 2)
    return rows


def build_json(rows: list[dict]) -> dict:
    return {
        "_metadata": {
            "source": "TfL Public Transport Accessibility Levels (PTAL), borough average",
            "url": "https://data.london.gov.uk/dataset/public-transport-accessibility-levels",
            "csv_url": PTAL_CSV_URL,
            "vintage": PTAL_VINTAGE,
            "definition": (
                "PTAL combines walk-time to stops, service frequency, and "
                "mode availability into a single accessibility score. Bands "
                "1a (very poor) to 6b (excellent). Score_0_to_100 is the "
                "log-transformed AvPTAI2015 min-max normalised across the 33 "
                "boroughs; log compresses the City of London outlier."
            ),
            "geography": "Greater London local authorities (32 London boroughs + City of London = 33 LADs)",
            "sdg_relevance": (
                "SDG 11.2 — access to safe, affordable, accessible, sustainable "
                "transport for all. PTAL is the GLA / TfL / Cabinet Office "
                "standard access measure."
            ),
        },
        "boroughs": {
            r["code"]: {
                "name": r["name"],
                "avptai_2015": r["avptai_2015"],
                "ptal_band": r["ptal_band"],
                "score_0_to_100": r["score_0_to_100"],
            }
            for r in rows
        },
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    text = _download()
    rows = _parse_csv(text)
    if len(rows) != 33:
        # 33 LADs (32 boroughs + City of London) is the canonical count.
        # Anything else means the upstream CSV shape changed; refusing
        # to overwrite a known-good output is safer than silently
        # truncating the agent's data source.
        logger.error(
            "Expected 33 boroughs, parsed %d. Refusing to overwrite "
            "%s with an incomplete dataset.",
            len(rows),
            OUTPUT_PATH,
        )
        return 1
    rows = _normalise(rows)
    payload = build_json(rows)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("Wrote %s (%d boroughs)", OUTPUT_PATH, len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
