"""Test Doctor Agent SSE endpoint.

Starts the API server once per module, sends queries to POST /agent/query,
validates SSE token streaming, source tracking, and agent_logs persistence.
Requires: pipeline data on disk + ANTHROPIC_API_KEY in environment.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import duckdb
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PORT = 18766
BASE = f"http://127.0.0.1:{PORT}"
TEST_DOCTOR_ACCESS_CODE = "test-doctor-code"

pytestmark = pytest.mark.api_key


# ============================================================
# Helpers
# ============================================================


def post_sse(path: str, body: dict) -> tuple[int | None, bytes]:
    """POST JSON and return (status_code, raw_bytes) for SSE responses."""
    url = f"{BASE}{path}"
    data = json.dumps(body).encode()
    req = Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        resp = urlopen(req, timeout=120)
        lines = []
        for line in resp:
            lines.append(line)
            if b"[DONE]" in line:
                break
        return resp.status, b"".join(lines)
    except HTTPError as e:
        return e.code, e.read()
    except (URLError, TimeoutError):
        return None, b""


def post_raw(path: str, raw_body: bytes, content_type: str = "application/json") -> int | None:
    """POST raw bytes and return status code only."""
    url = f"{BASE}{path}"
    req = Request(url, data=raw_body, headers={"Content-Type": content_type})
    try:
        resp = urlopen(req, timeout=10)
        return resp.status
    except HTTPError as e:
        return e.code
    except (URLError, TimeoutError):
        return None


def parse_sse(raw: bytes) -> list[dict | str]:
    """Parse SSE body into a list of JSON objects or raw strings."""
    events = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if line.startswith("data: "):
            payload = line[6:]
            try:
                events.append(json.loads(payload))
            except json.JSONDecodeError:
                events.append(payload)  # e.g. "[DONE]"
    return events


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture(scope="module", autouse=True)
def require_api_key():
    """Skip entire module if ANTHROPIC_API_KEY is not set."""
    # Load .env if present so tests work in local dev without exporting the key
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        for raw_line in env_file.read_text().splitlines():
            line = raw_line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set — skipping Doctor agent tests")


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
def camden_response(api_server):
    """Make the Camden SSE request once and share the parsed events."""
    status, body = post_sse("/agent/query", {
        "question": "How is Camden doing?",
        "access_code": TEST_DOCTOR_ACCESS_CODE,
    })
    return status, parse_sse(body)


@pytest.fixture(scope="module")
def london_response(api_server):
    """Make the London score SSE request once and share the parsed events."""
    status, body = post_sse(
        "/agent/query", {
            "question": "What is the overall London health score?",
            "access_code": TEST_DOCTOR_ACCESS_CODE,
        }
    )
    return status, parse_sse(body)


# ============================================================
# POST /agent/query — Camden question
# ============================================================


def test_camden_query_returns_200(camden_response):
    status, _ = camden_response
    assert status == 200, f"expected 200, got {status}"


def test_camden_query_has_sse_events(camden_response):
    _, events = camden_response
    assert len(events) > 0, f"no SSE events received"


def test_camden_query_has_token_events(camden_response):
    _, events = camden_response
    token_events = [e for e in events if isinstance(e, dict) and e.get("type") == "token"]
    assert len(token_events) > 0, f"no token events; got {len(token_events)}"


def test_camden_query_has_sources_event(camden_response):
    _, events = camden_response
    source_events = [e for e in events if isinstance(e, dict) and e.get("type") == "sources"]
    assert len(source_events) == 1, f"expected 1 sources event, got {len(source_events)}"


def test_camden_query_sources_is_list(camden_response):
    _, events = camden_response
    source_events = [e for e in events if isinstance(e, dict) and e.get("type") == "sources"]
    assert source_events
    sources = source_events[0].get("sources", [])
    assert isinstance(sources, list)


def test_camden_query_at_least_one_source(camden_response):
    _, events = camden_response
    source_events = [e for e in events if isinstance(e, dict) and e.get("type") == "sources"]
    assert source_events
    sources = source_events[0].get("sources", [])
    assert len(sources) > 0, f"sources list is empty"


def test_camden_query_source_has_type_field(camden_response):
    _, events = camden_response
    source_events = [e for e in events if isinstance(e, dict) and e.get("type") == "sources"]
    assert source_events
    sources = source_events[0].get("sources", [])
    assert sources
    assert "type" in sources[0]


def test_camden_query_source_has_tool_field(camden_response):
    _, events = camden_response
    source_events = [e for e in events if isinstance(e, dict) and e.get("type") == "sources"]
    assert source_events
    sources = source_events[0].get("sources", [])
    assert sources
    assert "tool" in sources[0]


def test_camden_query_has_done_sentinel(camden_response):
    _, events = camden_response
    done_events = [e for e in events if e == "[DONE]"]
    assert len(done_events) == 1, f"expected 1 [DONE], got {len(done_events)}"


def test_camden_query_answer_non_empty(camden_response):
    _, events = camden_response
    token_events = [e for e in events if isinstance(e, dict) and e.get("type") == "token"]
    answer = "".join(e["content"] for e in token_events)
    assert len(answer) > 0, "agent answer is empty"


# ============================================================
# POST /agent/query — London-wide question
# ============================================================


def test_london_query_returns_200(london_response):
    status, _ = london_response
    assert status == 200, f"expected 200, got {status}"


def test_london_query_used_get_london_score_tool(london_response):
    _, events = london_response
    source_events = [e for e in events if isinstance(e, dict) and e.get("type") == "sources"]
    assert source_events, "Expected agent to return sources event but got none"
    tools_used = [s["tool"] for s in source_events[0].get("sources", [])]
    assert "get_london_score" in tools_used, f"tools used: {tools_used}"


# ============================================================
# POST /agent/query — validation errors
# ============================================================


def test_empty_question_returns_422(api_server):
    status, _ = post_sse("/agent/query", {"question": ""})
    assert status == 422, f"expected 422 for empty question, got {status}"


def test_no_body_returns_422(api_server):
    status = post_raw(f"/agent/query", b"")
    assert status == 422, f"expected 422 for no body, got {status}"


# ============================================================
# agent_logs verification
# ============================================================


def test_agent_logs_has_rows(api_server, camden_response, london_response):
    """Verify agent_logs was written (depends on Camden + London queries running first)."""
    db_path = PROJECT_ROOT / "data" / "agent_logs.duckdb"
    if not db_path.exists():
        pytest.skip("agent_logs.duckdb not found")

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = con.execute(
            "SELECT id, query, tools_called, latency_ms FROM agent_logs "
            "ORDER BY timestamp DESC LIMIT 5"
        ).fetchall()
        assert len(rows) > 0, "agent_logs table is empty"
    except duckdb.CatalogException:
        pytest.fail("agent_logs table does not exist")
    finally:
        con.close()


def test_agent_logs_latest_has_id(api_server, camden_response, london_response):
    db_path = PROJECT_ROOT / "data" / "agent_logs.duckdb"
    if not db_path.exists():
        pytest.skip("agent_logs.duckdb not found")

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        row = con.execute(
            "SELECT id, query, tools_called, latency_ms FROM agent_logs "
            "ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        assert row[0] is not None, "latest log id is None"
    finally:
        con.close()


def test_agent_logs_latest_has_query(api_server, camden_response, london_response):
    db_path = PROJECT_ROOT / "data" / "agent_logs.duckdb"
    if not db_path.exists():
        pytest.skip("agent_logs.duckdb not found")

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        row = con.execute(
            "SELECT id, query, tools_called, latency_ms FROM agent_logs "
            "ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        assert row[1] is not None, "latest log query is None"
    finally:
        con.close()


def test_agent_logs_latest_has_tools_called(api_server, camden_response, london_response):
    db_path = PROJECT_ROOT / "data" / "agent_logs.duckdb"
    if not db_path.exists():
        pytest.skip("agent_logs.duckdb not found")

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        row = con.execute(
            "SELECT id, query, tools_called, latency_ms FROM agent_logs "
            "ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        assert row[2] is not None, "latest log tools_called is None"
    finally:
        con.close()


def test_agent_logs_latest_has_positive_latency(api_server, camden_response, london_response):
    db_path = PROJECT_ROOT / "data" / "agent_logs.duckdb"
    if not db_path.exists():
        pytest.skip("agent_logs.duckdb not found")

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        row = con.execute(
            "SELECT id, query, tools_called, latency_ms FROM agent_logs "
            "ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        assert row[3] is not None and row[3] > 0, f"latency_ms: {row[3]}"
    finally:
        con.close()
