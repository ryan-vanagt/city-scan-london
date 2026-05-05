"""
Tool: get_housing_affordability

Returns ONS Housing Affordability Ratio (median house price ÷ median
workplace-based earnings) for a London borough or for all 33 sorted by
ratio. London-specific structural stressor — annual cadence.

Data source:
    ONS Table 5c (median affordability ratio by Local Authority District).
    Refreshed by scripts/refresh_housing_affordability.py → data/static/housing_affordability.json.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DATA_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "static" / "housing_affordability.json"
)

_housing_data: dict | None = None


def _load_data() -> dict:
    global _housing_data
    if _housing_data is None:
        if not _DATA_PATH.exists():
            logger.error(
                "Housing affordability data not found at %s — run scripts/refresh_housing_affordability.py",
                _DATA_PATH,
            )
            return {}
        with open(_DATA_PATH, encoding="utf-8") as f:
            _housing_data = json.load(f)
    return _housing_data


def _resolve_borough(borough: str) -> tuple[str, dict] | None:
    if not borough or not borough.strip():
        return None

    data = _load_data()
    boroughs = data.get("boroughs", {})
    if not boroughs:
        return None

    query = borough.strip()

    if query in boroughs:
        return query, boroughs[query]

    query_lower = query.lower()

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


def _get_ratio_field(b: dict, year: int | None) -> float | None:
    """Find the latest-year ratio field in a borough record (e.g. 'ratio_2025')."""
    if year is not None:
        return b.get(f"ratio_{year}")
    # Fallback: scan keys
    for key, value in b.items():
        if isinstance(key, str) and key.startswith("ratio_") and not key.endswith("avg"):
            return value
    return None


def get_housing_affordability(borough: str | None = None) -> dict:
    """Get ONS Housing Affordability Ratio for a London borough or all 33.

    The ratio is median house price ÷ median workplace-based annual earnings
    (year ending September of the latest year). Higher ratio = less affordable.
    Annual cadence — refreshed once per year when ONS publishes a new vintage.

    With borough specified: returns that borough's current ratio + 5-year
    average.
    Without borough: returns all 33 boroughs sorted by ratio descending
    (most expensive first).

    Args:
        borough: Optional borough name or ONS code. If omitted, returns all.

    Returns:
        Dict with per-borough ratio data, or error dict if borough not found.
    """
    if borough is not None:
        borough = str(borough)[:100]
    data = _load_data()
    metadata = data.get("_metadata", {})
    year = metadata.get("year")

    if borough is None or not borough.strip():
        boroughs = data.get("boroughs", {})
        items = []
        for code, b in boroughs.items():
            ratio = _get_ratio_field(b, year)
            items.append({
                "borough_name": b.get("name"),
                "borough_code": code,
                "ratio": ratio,
                "ratio_5yr_avg": b.get("ratio_5yr_avg"),
            })
        items.sort(key=lambda x: -(x["ratio"] or 0))
        return {
            "year": year,
            "definition": metadata.get("definition"),
            "boroughs": items,
        }

    resolved = _resolve_borough(borough)
    if resolved is None:
        return {"error": f"Borough not found: '{borough}'"}

    code, b = resolved
    return {
        "borough_name": b.get("name"),
        "borough_code": code,
        "year": year,
        "ratio": _get_ratio_field(b, year),
        "ratio_5yr_avg": b.get("ratio_5yr_avg"),
        "definition": metadata.get("definition"),
    }
