"""
Tool: get_health_index

Returns the ONS Health Index for England (latest published year, 2021) for
a London borough. The Health Index is built from independent inputs (life
expectancy, mortality, mental-health prevalence, behaviours) — none from
CityScan's pipeline — so a comparison between the live composite and the
Health Index is convergent validity, not a tautology.

Data source:
    ONS Health Index for England (Table 2 — overall index).
    Refreshed by scripts/refresh_ons_health_index.py → data/static/ons_health_index.json.

Note: City of London (E09000001) is excluded from this dataset by ONS
convention. Requesting it returns a structured "not_in_dataset" response
rather than a null lookup.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DATA_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "static" / "ons_health_index.json"
)

_hi_data: dict | None = None
_CITY_OF_LONDON_CODE = "E09000001"


def _load_data() -> dict:
    global _hi_data
    if _hi_data is None:
        if not _DATA_PATH.exists():
            logger.error(
                "ONS Health Index data not found at %s — run scripts/refresh_ons_health_index.py",
                _DATA_PATH,
            )
            return {}
        with open(_DATA_PATH, encoding="utf-8") as f:
            _hi_data = json.load(f)
    return _hi_data


def _resolve_borough(borough: str) -> tuple[str, dict] | None:
    """Resolve a borough name or ONS code. Returns ("E09000001", None) for
    City of London so the caller can return a structured exclusion response."""
    if not borough or not borough.strip():
        return None

    query = borough.strip()
    query_lower = query.lower()

    # Special-case CoL by code or name
    if query == _CITY_OF_LONDON_CODE or query_lower in ("city of london", "col"):
        return _CITY_OF_LONDON_CODE, {}

    data = _load_data()
    boroughs = data.get("boroughs", {})
    if not boroughs:
        return None

    if query in boroughs:
        return query, boroughs[query]

    for code, b in boroughs.items():
        if b.get("name", "").lower() == query_lower:
            return code, b

    matches = [
        (code, b) for code, b in boroughs.items()
        if b.get("name", "").lower().startswith(query_lower)
    ]
    if len(matches) == 1:
        return matches[0]

    matches = [
        (code, b) for code, b in boroughs.items()
        if query_lower in b.get("name", "").lower()
    ]
    if len(matches) == 1:
        return matches[0]

    return None


def _get_score_field(b: dict, year: int | None) -> float | None:
    if year is not None:
        return b.get(f"score_{year}")
    for key, value in b.items():
        if isinstance(key, str) and key.startswith("score_") and key not in ("score_2020", "score_2015"):
            return value
    return None


def get_health_index(borough: str) -> dict:
    """Get the ONS Health Index for a London borough.

    The Health Index uses inputs that don't appear in CityScan's pipeline
    (life expectancy, mortality, mental-health prevalence, behaviours), so
    it provides an external convergent-validity reference — not a tautology
    against shared inputs as IMD would be.

    Returns the borough's latest score (England-2015 baseline = 100), plus
    2020 and 2015 scores for context. Higher = healthier.

    City of London is excluded from this dataset by ONS convention; for that
    borough, the response contains `"not_in_dataset": true` and a brief
    explanation.

    Args:
        borough: Borough name (e.g. 'Hackney') or ONS code (e.g. 'E09000012').

    Returns:
        Dict with health-index data, or error dict if borough not found, or
        a structured "not_in_dataset" response for City of London.
    """
    borough = str(borough)[:100]
    resolved = _resolve_borough(borough)
    if resolved is None:
        return {"error": f"Borough not found: '{borough}'"}

    code, b = resolved

    if code == _CITY_OF_LONDON_CODE:
        return {
            "borough_name": "City of London",
            "borough_code": code,
            "not_in_dataset": True,
            "reason": (
                "ONS excludes City of London from the Health Index by convention "
                "(small resident population, commuter-heavy workforce). Use the "
                "live CityScan composite for City of London health analysis."
            ),
        }

    metadata = _load_data().get("_metadata", {})
    year = metadata.get("year")

    return {
        "borough_name": b.get("name"),
        "borough_code": code,
        "year": year,
        "score": _get_score_field(b, year),
        "score_2020": b.get("score_2020"),
        "score_2015": b.get("score_2015"),
        "definition": metadata.get("definition"),
        "lag_note": metadata.get("lag_note"),
    }
