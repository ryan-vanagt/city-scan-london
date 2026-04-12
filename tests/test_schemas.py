"""Test pipeline/schemas.py — lookups, coord_to_borough, DDL."""

import re

import duckdb
import pytest

from pipeline.schemas import (
    BOROUGHS,
    BOROUGH_NAME_TO_CODE,
    LINE_TO_BOROUGHS,
    TRUST_TO_BOROUGHS,
    coord_to_borough,
    init_db,
)

# ---------------------------------------------------------------------------
# Borough lookups
# ---------------------------------------------------------------------------

def test_borough_count_is_33():
    assert len(BOROUGHS) == 33, f"got {len(BOROUGHS)}"


def test_all_codes_match_ons_format():
    ons_pattern = re.compile(r"^E090000\d{2}$")
    bad_codes = [c for c in BOROUGHS if not ons_pattern.match(c)]
    assert len(bad_codes) == 0, f"bad: {bad_codes}"


def test_every_borough_has_required_fields():
    missing_fields = [
        c for c, info in BOROUGHS.items()
        if not all(k in info for k in ("name", "lat", "lng"))
    ]
    assert len(missing_fields) == 0, f"missing: {missing_fields}"


def test_borough_name_to_code_has_33_entries():
    assert len(BOROUGH_NAME_TO_CODE) == 33


def test_reverse_lookup_roundtrips_for_all_33():
    reverse_ok = all(
        BOROUGH_NAME_TO_CODE.get(info["name"].lower()) == code
        for code, info in BOROUGHS.items()
    )
    assert reverse_ok

# ---------------------------------------------------------------------------
# TfL line lookups
# ---------------------------------------------------------------------------

EXPECTED_LINES = {
    "bakerloo", "central", "circle", "district", "hammersmith-city",
    "jubilee", "metropolitan", "northern", "piccadilly", "victoria",
    "waterloo-city",
}


def test_11_tfl_lines_present():
    assert set(LINE_TO_BOROUGHS.keys()) == EXPECTED_LINES, \
        f"got {set(LINE_TO_BOROUGHS.keys())}"


def test_all_tfl_borough_codes_valid():
    tfl_bad = [
        (line, code)
        for line, codes in LINE_TO_BOROUGHS.items()
        for code in codes
        if code not in BOROUGHS
    ]
    assert len(tfl_bad) == 0, f"orphans: {tfl_bad}"

# ---------------------------------------------------------------------------
# NHS trust lookups
# ---------------------------------------------------------------------------

def test_18_nhs_trusts_present():
    assert len(TRUST_TO_BOROUGHS) == 18, f"got {len(TRUST_TO_BOROUGHS)}"


def test_all_nhs_borough_codes_valid():
    nhs_bad = [
        (trust, code)
        for trust, codes in TRUST_TO_BOROUGHS.items()
        for code in codes
        if code not in BOROUGHS
    ]
    assert len(nhs_bad) == 0, f"orphans: {nhs_bad}"

# ---------------------------------------------------------------------------
# coord_to_borough landmarks
# ---------------------------------------------------------------------------

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


@pytest.mark.parametrize("name,lat,lng,expected", LANDMARKS)
def test_coord_to_borough_landmark(name, lat, lng, expected):
    result = coord_to_borough(lat, lng)
    assert result == expected, (
        f"{name}: got {result} ({BOROUGHS.get(result, {}).get('name', '?')})"
    )

# ---------------------------------------------------------------------------
# DuckDB DDL
# ---------------------------------------------------------------------------

def test_init_db_creates_silver_metrics_table():
    con = duckdb.connect(":memory:")
    init_db(con)
    tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
    con.close()
    assert "silver_metrics" in tables


def test_init_db_creates_gold_scores_table():
    con = duckdb.connect(":memory:")
    init_db(con)
    tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
    con.close()
    assert "gold_scores" in tables


def test_check_constraint_rejects_score_above_100():
    con = duckdb.connect(":memory:")
    init_db(con)
    with pytest.raises(Exception):
        con.execute(
            "INSERT INTO silver_metrics VALUES "
            "('E09000001','Test','2026-01-01T00:00:00+00','test',0,150,'test','2026-01-01T00:00:00+00','silver')"
        )
    con.close()


def test_check_constraint_rejects_score_below_0():
    con = duckdb.connect(":memory:")
    init_db(con)
    with pytest.raises(Exception):
        con.execute(
            "INSERT INTO silver_metrics VALUES "
            "('E09000001','Test','2026-01-01T00:00:00+00','test',0,-5,'test','2026-01-01T00:00:00+00','silver')"
        )
    con.close()
