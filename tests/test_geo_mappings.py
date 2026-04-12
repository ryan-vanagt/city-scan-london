"""Test geographic mapping accuracy — network-dependent (postcodes.io, TfL, NHS ODS).

Mark: pytest.mark.network — skip with `-m "not network"` when offline.
"""

import os
import time
from pathlib import Path

import pytest
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.network


# ============================================================
# Imports from project
# ============================================================

from pipeline.schemas import (
    BOROUGHS,
    BOROUGH_NAME_TO_CODE,
    LINE_TO_BOROUGHS,
    TRUST_TO_BOROUGHS,
    coord_to_borough,
)


# ============================================================
# Check 1: Borough centroids reverse-geocode correctly
# ============================================================


def test_borough_centroids_reverse_geocode():
    """All 33 borough centroids resolve back to the correct admin_district via postcodes.io."""
    geolocations = []
    borough_order = []
    for code, info in sorted(BOROUGHS.items()):
        geolocations.append({"longitude": info["lng"], "latitude": info["lat"]})
        borough_order.append((code, info["name"]))

    resp = requests.post(
        "https://api.postcodes.io/postcodes",
        json={"geolocations": geolocations},
        timeout=30,
    )
    resp.raise_for_status()
    results = resp.json()["result"]

    c1_pass = 0
    c1_near = 0
    failures = []

    for i, item in enumerate(results):
        code, expected_name = borough_order[i]
        if item.get("result") and len(item["result"]) > 0:
            actual = item["result"][0].get("admin_district", "")
            if actual.lower() == expected_name.lower():
                c1_pass += 1
                continue
        else:
            actual = "NO_RESULT"

        # Fallback: check nearest postcode within 2000m
        r2 = requests.get(
            "https://api.postcodes.io/postcodes",
            params={
                "lon": BOROUGHS[code]["lng"],
                "lat": BOROUGHS[code]["lat"],
                "limit": 1,
                "radius": 2000,
            },
            timeout=15,
        )
        if r2.json().get("result"):
            d = r2.json()["result"][0].get("admin_district", "")
            if d.lower() == expected_name.lower():
                c1_near += 1
                continue

        failures.append(f"{code} ({expected_name}): got {actual!r}")

    total = c1_pass + c1_near
    assert total == 33, (
        f"Only {total}/33 centroids resolved correctly.\nFailures:\n"
        + "\n".join(failures)
    )


# ============================================================
# Check 2: TfL line→borough matches live API
# ============================================================


def test_tfl_line_borough_mappings():
    """All 11 TfL tube line→borough mappings match what TfL StopPoints returns."""
    tfl_key = os.environ.get("TFL_APP_KEY", "")
    tfl_params = {"app_key": tfl_key} if tfl_key else {}
    failures = []
    lines_ok = 0

    for line_id, our_boroughs in sorted(LINE_TO_BOROUGHS.items()):
        resp = requests.get(
            f"https://api.tfl.gov.uk/Line/{line_id}/StopPoints",
            params=tfl_params,
            timeout=30,
        )
        resp.raise_for_status()
        stations = resp.json()
        coords = [
            {"latitude": s["lat"], "longitude": s["lon"]}
            for s in stations
            if s.get("lat") and s.get("lon")
        ]

        actual_boroughs: set[str] = set()
        for i in range(0, len(coords), 100):
            batch = coords[i : i + 100]
            geo_resp = requests.post(
                "https://api.postcodes.io/postcodes",
                json={"geolocations": batch},
                timeout=30,
            )
            geo_resp.raise_for_status()
            for item in geo_resp.json()["result"]:
                if item.get("result") and len(item["result"]) > 0:
                    district = item["result"][0].get("admin_district", "")
                    code = BOROUGH_NAME_TO_CODE.get(district.lower())
                    if code:
                        actual_boroughs.add(code)

        our_set = set(our_boroughs)
        missing = actual_boroughs - our_set
        extra = our_set - actual_boroughs

        if not missing and not extra:
            lines_ok += 1
        else:
            detail_parts = []
            if missing:
                detail_parts.append(
                    f"missing: {[BOROUGHS[c]['name'] for c in sorted(missing)]}"
                )
            if extra:
                detail_parts.append(
                    f"extra: {[BOROUGHS[c]['name'] for c in sorted(extra)]}"
                )
            failures.append(f"{line_id}: {'; '.join(detail_parts)}")

        time.sleep(0.3)

    assert lines_ok == 11, (
        f"Only {lines_ok}/11 TfL line mappings correct.\nFailures:\n"
        + "\n".join(failures)
    )


# ============================================================
# Check 3: NHS trust HQ in mapping
# ============================================================


def test_nhs_trust_hq_mappings():
    """All 18 NHS trust HQ postcodes fall within a borough in TRUST_TO_BOROUGHS."""
    hq_ok = 0
    failures = []

    for org_code, our_boroughs in sorted(TRUST_TO_BOROUGHS.items()):
        time.sleep(0.3)
        try:
            r = requests.get(
                f"https://directory.spineservices.nhs.uk/ORD/2-0-0/organisations/{org_code}",
                timeout=15,
            )
            if r.status_code != 200:
                continue
            org = r.json().get("Organisation", {})
            pc = org.get("GeoLoc", {}).get("Location", {}).get("PostCode", "").strip()
            if not pc:
                continue
            pr = requests.get(f"https://api.postcodes.io/postcodes/{pc}", timeout=15)
            if pr.status_code != 200:
                continue
            district = pr.json()["result"].get("admin_district", "")
            hq_code = BOROUGH_NAME_TO_CODE.get(district.lower())
            if hq_code and hq_code in set(our_boroughs):
                hq_ok += 1
            else:
                name = org.get("Name", "?")
                failures.append(f"{org_code} ({name[:30]}): HQ in {district!r}, not in mapping")
        except Exception as exc:
            failures.append(f"{org_code}: {str(exc)[:60]}")

    assert hq_ok == 18, (
        f"Only {hq_ok}/18 NHS trust HQs found in mapping.\nFailures:\n"
        + "\n".join(failures)
    )


# ============================================================
# Check 4: coord_to_borough landmarks
# ============================================================


LANDMARKS = [
    ("Big Ben", 51.5007, -0.1246, "E09000033"),
    ("Tower of London", 51.5081, -0.0759, "E09000030"),
    ("Buckingham Palace", 51.5014, -0.1419, "E09000033"),
    ("O2 Arena", 51.5030, 0.0032, "E09000011"),
    ("Wembley Stadium", 51.5560, -0.2795, "E09000005"),
    ("Crystal Palace", 51.4214, -0.0731, "E09000006"),
    ("Heathrow T5", 51.4723, -0.4889, "E09000017"),
    ("Canary Wharf", 51.5054, -0.0235, "E09000030"),
    ("Brixton Market", 51.4613, -0.1145, "E09000022"),
    ("Camden Market", 51.5413, -0.1436, "E09000007"),
]


@pytest.mark.parametrize("name,lat,lng,expected_code", LANDMARKS)
def test_coord_to_borough_landmark(name, lat, lng, expected_code):
    """coord_to_borough resolves well-known London landmarks to the correct borough."""
    result = coord_to_borough(lat, lng)
    got_name = BOROUGHS[result]["name"] if result else "None"
    assert result == expected_code, (
        f"{name}: expected {expected_code}, got {result!r} ({got_name})"
    )
