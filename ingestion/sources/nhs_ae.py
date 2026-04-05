"""
NHS England A&E waiting times data source collector.

Scrapes the NHS England statistics page using BeautifulSoup to discover the
latest monthly CSV download link (URL changes each month), then downloads
and parses the CSV for London NHS trusts.

Data is published monthly (~2 months lag). Contributes to the immune system
score alongside crime data. No API key required — fully public data.
Raw responses are saved to /data/bronze/nhs_ae/ as timestamped JSON.
"""

import csv
import io
import logging
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

NHS_STATS_BASE = (
    "https://www.england.nhs.uk/statistics/statistical-work-areas/"
    "ae-waiting-times-and-activity/"
)


def _candidate_stats_pages() -> list[str]:
    """Return candidate NHS England A&E statistics page URLs, most recent first.

    Tries the current financial year first, then the previous one.  This handles
    the transition window at the start of April when NHS England hasn't yet
    published the new year's page (typically a few weeks late).

    The NHS financial year runs April–March, so the year suffix increments each April.
    Example: April 2026–March 2027 → 'ae-attendances-and-emergency-admissions-2026-27/'.
    """
    now = datetime.now(timezone.utc)
    year_start = now.year if now.month >= 4 else now.year - 1
    candidates = []
    for ys in (year_start, year_start - 1):
        ye_short = str(ys + 1)[-2:]
        candidates.append(
            f"{NHS_STATS_BASE}ae-attendances-and-emergency-admissions-{ys}-{ye_short}/"
        )
    return candidates

# London NHS trust name fragments for filtering the national CSV
LONDON_TRUST_FRAGMENTS = [
    "Barts Health",
    "Guy's and St Thomas",
    "King's College Hospital",
    "Imperial College",
    "Royal Free",
    "University College London",
    "Whittington",
    "St George's",
    "Lewisham and Greenwich",
    "London North West",
    "Homerton",
    "Chelsea and Westminster",
    "Epsom and St Helier",
    "Croydon",
    "Kingston",
    "Barking, Havering",
    "Hillingdon",
]


def _latest_csv_url() -> str | None:
    """Scrape the NHS England statistics page to find the latest A&E CSV URL.

    The CSV URL changes every month so we cannot hardcode it — we discover
    it dynamically by parsing the statistics page with BeautifulSoup.

    Returns:
        URL string of the most recent CSV file, or None on failure.
    """
    for url in _candidate_stats_pages():
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            break
        except requests.RequestException as exc:
            logger.warning("NHS A&E: statistics page unavailable (%s): %s", url, exc)
    else:
        logger.error("NHS A&E: no statistics page responded successfully")
        return None

    soup = BeautifulSoup(response.text, "lxml")
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if href.endswith(".csv"):
            # First CSV link on the page is always the most recent month
            logger.info("NHS A&E: found CSV at %s", href)
            return href

    logger.error("NHS A&E: no CSV link found on statistics page")
    return None


def fetch() -> dict:
    """Fetch London NHS trust A&E performance data from NHS England.

    Scrapes the statistics page to find the latest CSV, downloads it,
    and filters for London trusts. Calculates % seen within 4 hours
    from raw Type 1 attendance counts.

    Returns:
        Dict with 'results' (London trust rows), 'period', and 'fetched_at'.

    Raises:
        RuntimeError: If no CSV URL can be found on the statistics page.
        requests.HTTPError: If the CSV download fails.
        requests.RequestException: On network or timeout errors.
    """
    csv_url = _latest_csv_url()
    if not csv_url:
        raise RuntimeError("NHS A&E: could not find CSV download link")

    try:
        response = requests.get(csv_url, timeout=60)
        response.raise_for_status()
    except requests.HTTPError as e:
        logger.error("NHS A&E: CSV download HTTP error: %s", e)
        raise
    except requests.RequestException as e:
        logger.error("NHS A&E: CSV download failed: %s", e)
        raise

    reader = csv.DictReader(io.StringIO(response.text))
    results = []
    period = None

    for row in reader:
        org_name = row.get("Org name", "").strip()

        # Filter to London trusts only
        if not any(fragment.lower() in org_name.lower() for fragment in LONDON_TRUST_FRAGMENTS):
            continue

        if period is None:
            period = row.get("Period", "").strip()

        # Type 1 = major A&E departments (most clinically significant)
        try:
            total = int(row.get("A&E attendances Type 1") or 0)
            over_4hrs = int(row.get("Attendances over 4hrs Type 1") or 0)
        except ValueError:
            logger.warning("NHS A&E: skipping %s — non-numeric attendance data", org_name)
            continue

        if total == 0:
            continue  # trust has no Type 1 A&E this period

        pct_within_4hrs = round((total - over_4hrs) / total * 100, 1)

        results.append({
            "org_name": org_name,
            "org_code": row.get("Org Code", "").strip(),
            "period": period,
            "total_type1_attendances": total,
            "over_4hrs_type1": over_4hrs,
            "pct_within_4hrs": pct_within_4hrs,
        })

    logger.info(
        "NHS A&E: retrieved %d London trust rows for %s",
        len(results),
        period or "unknown period",
    )

    return {
        "results": results,
        "period": period,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
