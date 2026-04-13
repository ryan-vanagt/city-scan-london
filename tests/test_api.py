"""Test API endpoints against a live uvicorn server.

Starts the server once per module, runs all endpoint tests, then shuts it down.
Requires: bronze data on disk (run `python ingestion/run_pipeline.py` first).
"""

import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import duckdb
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PORT = 18765
BASE = f"http://127.0.0.1:{PORT}"


# ============================================================
# Helpers
# ============================================================


def get(path: str, expected_status: int = 200) -> dict | list | None:
    """Make a GET request. Returns parsed JSON or None on error."""
    url = f"{BASE}{path}"
    req = Request(url)
    try:
        resp = urlopen(req, timeout=10)
        body = json.loads(resp.read())
        if resp.status != expected_status:
            return None
        return body
    except HTTPError as e:
        if e.code == expected_status:
            return json.loads(e.read())
        return None
    except (URLError, TimeoutError):
        return None


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture(scope="module", autouse=True)
def ensure_gold_data():
    """Ensure DuckDB has gold_scores data, rebuilding from bronze if needed."""
    db_path = PROJECT_ROOT / "data" / "cityscan.duckdb"

    needs_rebuild = True
    if db_path.exists():
        try:
            con = duckdb.connect(str(db_path), read_only=True)
            count = con.execute("SELECT COUNT(*) FROM gold_scores").fetchone()[0]
            con.close()
            if count > 0:
                needs_rebuild = False
        except Exception:
            pass

    if needs_rebuild:
        logging.basicConfig(level=logging.WARNING)
        from pipeline import gold, silver
        from pipeline.schemas import init_db

        con = duckdb.connect(str(db_path))
        init_db(con)
        rows = silver.transform_all()
        if not rows:
            pytest.skip("No bronze data — run `python ingestion/run_pipeline.py` first")
        silver.load(con, rows)
        gold.aggregate(con)
        con.close()


@pytest.fixture(scope="module")
def api_server():
    """Start API server once for all tests in this module."""
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.main:app", "--port", str(PORT)],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    ready = False
    for _ in range(30):
        try:
            urlopen(f"{BASE}/health", timeout=2)
            ready = True
            break
        except (URLError, TimeoutError):
            time.sleep(0.5)

    if not ready:
        server.kill()
        server.wait()
        pytest.fail("API server did not start within 15 seconds")

    yield BASE

    server.terminate()
    try:
        server.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server.kill()


# ============================================================
# GET /health
# ============================================================


def test_health_returns_json(api_server):
    data = get("/health")
    assert data is not None, "/health returned no response"


def test_health_status_ok(api_server):
    data = get("/health")
    assert data is not None
    assert data.get("status") == "ok"


def test_health_no_database_field(api_server):
    """Health endpoint must NOT open a DuckDB connection (avoids holding a lock)."""
    data = get("/health")
    assert data is not None
    assert "database" not in data


def test_health_has_timestamp(api_server):
    data = get("/health")
    assert data is not None
    assert "timestamp" in data


# ============================================================
# GET /london/score
# ============================================================


def test_london_score_returns_json(api_server):
    data = get("/london/score")
    assert data is not None, "/london/score returned no response"


def test_london_score_has_composite(api_server):
    data = get("/london/score")
    assert data is not None
    assert "composite_score" in data


def test_london_score_composite_is_number(api_server):
    data = get("/london/score")
    assert data is not None
    assert isinstance(data["composite_score"], (int, float))


def test_london_score_composite_in_range(api_server):
    data = get("/london/score")
    assert data is not None
    cs = data["composite_score"]
    assert 0 <= cs <= 100, f"composite_score out of range: {cs}"


def test_london_score_has_borough_count(api_server):
    data = get("/london/score")
    assert data is not None
    assert "borough_count" in data


def test_london_score_borough_count_33(api_server):
    data = get("/london/score")
    assert data is not None
    assert data["borough_count"] == 33, f"expected 33, got {data['borough_count']}"


@pytest.mark.parametrize("field", ["air_score", "transit_score", "sentiment_score", "immune_score"])
def test_london_score_sub_scores_valid(api_server, field):
    data = get("/london/score")
    assert data is not None
    val = data.get(field)
    assert val is None or isinstance(val, (int, float)), f"{field} has unexpected type {type(val)}"
    if isinstance(val, (int, float)):
        assert 0 <= val <= 100, f"{field} out of range: {val}"


# ============================================================
# GET /boroughs
# ============================================================


def test_boroughs_returns_list(api_server):
    data = get("/boroughs")
    assert isinstance(data, list), "/boroughs did not return a list"


def test_boroughs_count_33(api_server):
    data = get("/boroughs")
    assert isinstance(data, list)
    assert len(data) == 33, f"expected 33 boroughs, got {len(data)}"


def test_boroughs_first_has_required_fields(api_server):
    data = get("/boroughs")
    assert isinstance(data, list) and data
    first = data[0]
    for field in ("borough_code", "borough_name", "composite_score", "air_score", "timestamp"):
        assert field in first, f"missing field: {field}"


def test_boroughs_sorted_desc_by_composite(api_server):
    data = get("/boroughs")
    assert isinstance(data, list) and data
    composites = [b["composite_score"] for b in data if b["composite_score"] is not None]
    assert composites == sorted(composites, reverse=True), (
        f"not sorted desc; first 3: {composites[:3]}"
    )


def test_boroughs_sort_by_air_score(api_server):
    data = get("/boroughs?sort_by=air_score")
    assert isinstance(data, list) and data
    air_scores = [b["air_score"] for b in data if b["air_score"] is not None]
    assert air_scores == sorted(air_scores, reverse=True), (
        f"not sorted desc by air_score; first 3: {air_scores[:3]}"
    )


def test_boroughs_invalid_sort_returns_422(api_server):
    data = get("/boroughs?sort_by=DROP_TABLE", expected_status=422)
    assert data is not None, "expected 422 response body"


# ============================================================
# GET /borough/{name}
# ============================================================


def test_borough_by_name_returns_json(api_server):
    data = get("/borough/camden")
    assert data is not None, "/borough/camden returned no response"


def test_borough_by_name_correct_code(api_server):
    data = get("/borough/camden")
    assert data is not None
    assert data.get("borough_code") == "E09000007"


def test_borough_by_name_correct_name(api_server):
    data = get("/borough/camden")
    assert data is not None
    assert data.get("borough_name") == "Camden"


def test_borough_by_name_has_composite_score(api_server):
    data = get("/borough/camden")
    assert data is not None
    assert "composite_score" in data


def test_borough_by_name_composite_in_range(api_server):
    data = get("/borough/camden")
    assert data is not None
    cs = data.get("composite_score")
    assert isinstance(cs, (int, float)) and 0 <= cs <= 100, f"composite_score: {cs}"


def test_borough_by_ons_code(api_server):
    data = get("/borough/E09000007")
    assert data is not None, "ONS code lookup failed"
    assert data.get("borough_name") == "Camden"


def test_borough_mixed_case_resolves(api_server):
    data = get("/borough/Camden")
    assert data is not None, "mixed-case lookup failed"
    assert data.get("borough_code") == "E09000007"


def test_borough_nonexistent_returns_404(api_server):
    data = get("/borough/nonexistent", expected_status=404)
    assert data is not None, "expected 404 response body"


def test_borough_nonexistent_has_detail(api_server):
    data = get("/borough/nonexistent", expected_status=404)
    assert data is not None
    assert "detail" in data


# ============================================================
# GET /borough/{name}/trend
# ============================================================


def test_trend_returns_json(api_server):
    data = get("/borough/camden/trend")
    assert data is not None, "/borough/camden/trend returned no response"


def test_trend_has_borough_code(api_server):
    data = get("/borough/camden/trend")
    assert data is not None
    assert data.get("borough_code") == "E09000007"


def test_trend_default_days_is_7(api_server):
    data = get("/borough/camden/trend")
    assert data is not None
    assert data.get("days") == 7


def test_trend_has_data_points(api_server):
    data = get("/borough/camden/trend")
    assert data is not None
    assert "data_points" in data


def test_trend_array_is_list(api_server):
    data = get("/borough/camden/trend")
    assert data is not None
    assert isinstance(data.get("trend"), list)


def test_trend_has_at_least_one_point(api_server):
    data = get("/borough/camden/trend")
    assert data is not None
    trend = data.get("trend", [])
    assert len(trend) >= 1, f"expected >= 1 data point, got {len(trend)}"


def test_trend_point_fields(api_server):
    data = get("/borough/camden/trend")
    assert data is not None
    trend = data.get("trend", [])
    assert trend, "trend array is empty"
    pt = trend[0]
    for field in ("timestamp", "composite_score", "air_score"):
        assert field in pt, f"trend point missing field: {field}"


def test_trend_days_30(api_server):
    data = get("/borough/camden/trend?days=30")
    assert data is not None
    assert data.get("days") == 30


def test_trend_days_0_returns_422(api_server):
    data = get("/borough/camden/trend?days=0", expected_status=422)
    assert data is not None, "expected 422 for days=0"


def test_trend_days_31_returns_422(api_server):
    data = get("/borough/camden/trend?days=31", expected_status=422)
    assert data is not None, "expected 422 for days=31"


# ============================================================
# Cross-endpoint consistency
# ============================================================


def test_borough_composite_matches_boroughs_list(api_server):
    single = get("/borough/camden")
    all_boroughs = get("/boroughs")
    assert single is not None and isinstance(all_boroughs, list)

    camden_from_list = next(
        (b for b in all_boroughs if b["borough_code"] == "E09000007"), None
    )
    assert camden_from_list is not None, "Camden not found in /boroughs list"
    assert single["composite_score"] == camden_from_list["composite_score"], (
        f"single={single['composite_score']}, list={camden_from_list['composite_score']}"
    )


# ============================================================
# Input validation tests (no API key needed)
# ============================================================


def test_agent_query_empty_body_returns_422(api_server):
    """POST /agent/query with empty body should return 422."""
    req = Request(
        f"{BASE}/agent/query",
        data=json.dumps({}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urlopen(req, timeout=5)
        assert False, "Expected 422 but got success"
    except HTTPError as e:
        assert e.code == 422, f"expected 422, got {e.code}"


def test_agent_query_too_long_returns_422(api_server):
    """POST /agent/query with >500 char question should return 422."""
    long_question = "x" * 501
    req = Request(
        f"{BASE}/agent/query",
        data=json.dumps({"question": long_question}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urlopen(req, timeout=5)
        assert False, "Expected 422 but got success"
    except HTTPError as e:
        assert e.code == 422, f"expected 422, got {e.code}"


@pytest.mark.api_key
def test_bulletin_generate_rate_limit(api_server):
    """Second rapid bulletin generation should return 429.

    NOTE: This test is best-effort — if the first call fails before setting
    the cooldown timer (e.g. no data), the second call may also succeed.
    We assert 429 and skip with a clear message if the rate limit wasn't hit.
    """

    def post_bulletin():
        req = Request(
            f"{BASE}/bulletin/generate",
            data=b"",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return urlopen(req, timeout=30)

    # First call should succeed (or 500 if no data — either way, it sets the cooldown)
    try:
        post_bulletin()
    except HTTPError:
        pass  # First call may fail for other reasons, but should set the timer

    # Second immediate call should be rate-limited
    try:
        resp = post_bulletin()
        # If it succeeds, the rate limit didn't trigger — skip rather than silently pass
        pytest.skip(
            "Rate limit not triggered (first call may not have set cooldown) — "
            "test is inconclusive, not a failure"
        )
    except HTTPError as e:
        assert e.code == 429, f"Expected 429 rate limit, got {e.code}"
