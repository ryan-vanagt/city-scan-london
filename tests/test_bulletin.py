"""Test Bulletin Agent generation endpoint.

Starts the API server once per module, triggers bulletin generation, validates
the output markdown and logging. Cleans up the generated bulletin file after
all tests complete.
Requires: pipeline data on disk + ANTHROPIC_API_KEY in environment.
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import duckdb
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PORT = 18768
BASE = f"http://127.0.0.1:{PORT}"
TEST_DOCTOR_ACCESS_CODE = "test-doctor-code"

pytestmark = pytest.mark.api_key


# ============================================================
# Helpers
# ============================================================


def post_json(path: str, body: dict | None = None) -> tuple[int | None, dict | None]:
    """POST JSON and return (status_code, parsed_json)."""
    url = f"{BASE}{path}"
    data = json.dumps(body or {}).encode()
    req = Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        resp = urlopen(req, timeout=120)
        return resp.status, json.loads(resp.read())
    except HTTPError as e:
        return e.code, json.loads(e.read())
    except (URLError, TimeoutError):
        return None, None


def get(path: str) -> tuple[int | None, dict | None]:
    """GET request, return (status_code, parsed_json)."""
    url = f"{BASE}{path}"
    req = Request(url)
    try:
        resp = urlopen(req, timeout=10)
        return resp.status, json.loads(resp.read())
    except HTTPError as e:
        return e.code, json.loads(e.read())
    except (URLError, TimeoutError):
        return None, None


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture(scope="module", autouse=True)
def require_api_key():
    """Skip entire module if ANTHROPIC_API_KEY is not set."""
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        for raw_line in env_file.read_text().splitlines():
            line = raw_line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set — skipping Bulletin agent tests")


@pytest.fixture(scope="module")
def api_server():
    """Start API server once for all tests in this module."""
    env = {**os.environ, "DOCTOR_ACCESS_CODE": TEST_DOCTOR_ACCESS_CODE}
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.main:app", "--port", str(PORT)],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
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


@pytest.fixture(scope="module")
def generated_bulletin(api_server):
    """Generate a bulletin once and clean it up after the module finishes."""
    status, data = post_json("/bulletin/generate", {"access_code": TEST_DOCTOR_ACCESS_CODE})
    yield status, data

    # Cleanup: remove the bulletin file written during this test run
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    bulletin_file = PROJECT_ROOT / "data" / "bulletins" / f"{today}.md"
    if bulletin_file.exists():
        try:
            bulletin_file.unlink()
        except OSError:
            pass


# ============================================================
# POST /bulletin/generate
# ============================================================


def test_bulletin_generate_returns_200(generated_bulletin):
    status, _ = generated_bulletin
    assert status == 200, f"expected 200, got {status}"


def test_bulletin_generate_has_date_field(generated_bulletin):
    _, data = generated_bulletin
    assert data is not None
    assert "date" in data


def test_bulletin_generate_has_content_field(generated_bulletin):
    _, data = generated_bulletin
    assert data is not None
    assert "content" in data


def test_bulletin_date_is_iso_format(generated_bulletin):
    _, data = generated_bulletin
    assert data is not None
    date_str = data.get("date", "")
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", date_str), f"date not YYYY-MM-DD: {date_str!r}"


def test_bulletin_content_non_empty(generated_bulletin):
    _, data = generated_bulletin
    assert data is not None
    content = data.get("content", "")
    assert len(content) > 100, f"content too short: {len(content)} chars"


def test_bulletin_content_has_health_or_bulletin(generated_bulletin):
    _, data = generated_bulletin
    assert data is not None
    content_lower = data.get("content", "").lower()
    assert "bulletin" in content_lower or "health" in content_lower


def test_bulletin_content_mentions_score(generated_bulletin):
    _, data = generated_bulletin
    assert data is not None
    content_lower = data.get("content", "").lower()
    assert "score" in content_lower or "overall" in content_lower


# ============================================================
# Bulletin file saved to disk
# ============================================================


def test_bulletin_file_exists_on_disk(generated_bulletin):
    _, data = generated_bulletin
    assert data is not None
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    bulletin_path = PROJECT_ROOT / "data" / "bulletins" / f"{today}.md"
    assert bulletin_path.exists(), f"expected file at {bulletin_path}"


def test_bulletin_file_content_matches_response(generated_bulletin):
    _, data = generated_bulletin
    assert data is not None
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    bulletin_path = PROJECT_ROOT / "data" / "bulletins" / f"{today}.md"
    if not bulletin_path.exists():
        pytest.skip("bulletin file not on disk")
    file_content = bulletin_path.read_text(encoding="utf-8")
    assert file_content == data.get("content", "")


def test_bulletin_file_has_sufficient_length(generated_bulletin):
    _, data = generated_bulletin
    assert data is not None
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    bulletin_path = PROJECT_ROOT / "data" / "bulletins" / f"{today}.md"
    if not bulletin_path.exists():
        pytest.skip("bulletin file not on disk")
    assert len(bulletin_path.read_text(encoding="utf-8")) > 100


# ============================================================
# GET /bulletin/latest
# ============================================================


def test_bulletin_latest_returns_200(api_server, generated_bulletin):
    status, _ = get("/bulletin/latest")
    assert status == 200, f"expected 200, got {status}"


def test_bulletin_latest_has_date(api_server, generated_bulletin):
    _, latest = get("/bulletin/latest")
    assert latest is not None
    assert "date" in latest


def test_bulletin_latest_has_content(api_server, generated_bulletin):
    _, latest = get("/bulletin/latest")
    assert latest is not None
    assert "content" in latest


def test_bulletin_latest_date_matches_generated(api_server, generated_bulletin):
    _, gen_data = generated_bulletin
    _, latest = get("/bulletin/latest")
    assert latest is not None and gen_data is not None
    assert latest.get("date") == gen_data.get("date"), (
        f"latest date {latest.get('date')!r} != generated date {gen_data.get('date')!r}"
    )


# ============================================================
# bulletin_logs verification
# ============================================================


def test_bulletin_logs_has_rows(api_server, generated_bulletin):
    log_db_path = PROJECT_ROOT / "data" / "agent_logs.duckdb"
    if not log_db_path.exists():
        pytest.skip("agent_logs.duckdb not found")

    con = duckdb.connect(str(log_db_path), read_only=True)
    try:
        rows = con.execute(
            "SELECT id, trigger, output_path, latency_ms FROM bulletin_logs "
            "ORDER BY timestamp DESC LIMIT 5"
        ).fetchall()
        assert len(rows) > 0, "bulletin_logs table is empty"
    except duckdb.CatalogException:
        pytest.fail("bulletin_logs table does not exist")
    finally:
        con.close()


def test_bulletin_logs_latest_has_id(api_server, generated_bulletin):
    log_db_path = PROJECT_ROOT / "data" / "agent_logs.duckdb"
    if not log_db_path.exists():
        pytest.skip("agent_logs.duckdb not found")

    con = duckdb.connect(str(log_db_path), read_only=True)
    try:
        row = con.execute(
            "SELECT id, trigger, output_path, latency_ms FROM bulletin_logs "
            "ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        assert row and row[0] is not None, "latest bulletin log id is None"
    finally:
        con.close()


def test_bulletin_logs_trigger_is_manual(api_server, generated_bulletin):
    log_db_path = PROJECT_ROOT / "data" / "agent_logs.duckdb"
    if not log_db_path.exists():
        pytest.skip("agent_logs.duckdb not found")

    con = duckdb.connect(str(log_db_path), read_only=True)
    try:
        row = con.execute(
            "SELECT trigger FROM bulletin_logs ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        assert row and row[0] == "manual", f"expected trigger='manual', got {row[0]!r}"
    finally:
        con.close()


def test_bulletin_logs_has_output_path(api_server, generated_bulletin):
    log_db_path = PROJECT_ROOT / "data" / "agent_logs.duckdb"
    if not log_db_path.exists():
        pytest.skip("agent_logs.duckdb not found")

    con = duckdb.connect(str(log_db_path), read_only=True)
    try:
        row = con.execute(
            "SELECT output_path FROM bulletin_logs ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        assert row and row[0] is not None, "latest bulletin log output_path is None"
    finally:
        con.close()


def test_bulletin_logs_has_positive_latency(api_server, generated_bulletin):
    log_db_path = PROJECT_ROOT / "data" / "agent_logs.duckdb"
    if not log_db_path.exists():
        pytest.skip("agent_logs.duckdb not found")

    con = duckdb.connect(str(log_db_path), read_only=True)
    try:
        row = con.execute(
            "SELECT latency_ms FROM bulletin_logs ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        assert row and row[0] is not None and row[0] > 0, f"latency_ms: {row[0] if row else None}"
    finally:
        con.close()


# ============================================================
# Content safety check
# ============================================================


def test_bulletin_no_selftext_in_content(generated_bulletin):
    _, data = generated_bulletin
    assert data is not None
    assert "selftext" not in data.get("content", "").lower()


def test_bulletin_no_trailtext_in_content(generated_bulletin):
    _, data = generated_bulletin
    assert data is not None
    assert "trailText" not in data.get("content", "")
