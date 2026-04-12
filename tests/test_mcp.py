"""Test MCP server against a live process.

Starts the MCP server once per module, runs tool integration tests via
JSON-RPC over HTTP, then shuts it down.
Requires: pipeline data on disk (run `python ingestion/run_pipeline.py` first).
"""

import json
import logging
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
PORT = 18767
BASE = f"http://127.0.0.1:{PORT}"
MCP_ENDPOINT = f"{BASE}/mcp"


# ============================================================
# Helpers
# ============================================================


def _parse_sse_response(raw: bytes) -> dict | None:
    """Parse a Server-Sent Events response and return the last JSON-RPC message.

    SSE format: ``event: message\\ndata: {json}\\n\\n``
    May also be plain JSON (non-SSE) in some cases.
    """
    text = raw.decode("utf-8", errors="replace")
    last_data = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("data:"):
            payload = stripped[5:].strip()
            if payload:
                last_data = payload
    if last_data:
        try:
            return json.loads(last_data)
        except json.JSONDecodeError:
            return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


class MCPClient:
    """Stateful JSON-RPC client that tracks the MCP session ID."""

    def __init__(self) -> None:
        self._session_id: str | None = None
        self._request_id = 0

    def _next_id(self) -> str:
        self._request_id += 1
        return str(self._request_id)

    def request(self, method: str, params: dict | None = None) -> dict | None:
        """Send a JSON-RPC request to the MCP server, return parsed response."""
        body = {"jsonrpc": "2.0", "id": self._next_id(), "method": method}
        if params is not None:
            body["params"] = params

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["mcp-session-id"] = self._session_id

        data = json.dumps(body).encode("utf-8")
        req = Request(MCP_ENDPOINT, data=data, headers=headers, method="POST")
        try:
            resp = urlopen(req, timeout=30)
            sid = resp.headers.get("mcp-session-id")
            if sid:
                self._session_id = sid
            return _parse_sse_response(resp.read())
        except HTTPError as e:
            return _parse_sse_response(e.read())
        except (URLError, TimeoutError):
            return None

    @property
    def session_id(self) -> str | None:
        return self._session_id


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
def mcp_client():
    """Start MCP server and return an initialised MCPClient, stop server afterwards."""
    os.environ["MCP_PORT"] = str(PORT)

    server = subprocess.Popen(
        [sys.executable, "mcp_server/server.py"],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, "MCP_PORT": str(PORT)},
    )

    client = MCPClient()

    # Wait for readiness by polling initialize
    ready = False
    for _ in range(30):
        try:
            req = Request(
                MCP_ENDPOINT,
                data=json.dumps({
                    "jsonrpc": "2.0",
                    "id": "0",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "clientInfo": {"name": "test-mcp", "version": "1.0.0"},
                    },
                }).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
                method="POST",
            )
            resp = urlopen(req, timeout=5)
            sid = resp.headers.get("mcp-session-id")
            if sid:
                client._session_id = sid
            parsed = _parse_sse_response(resp.read())
            if parsed and "result" in parsed:
                ready = True
                break
        except (URLError, TimeoutError, HTTPError):
            time.sleep(0.5)

    if not ready:
        server.kill()
        server.wait()
        pytest.fail("MCP server did not start within 15 seconds")

    yield client

    server.terminate()
    try:
        server.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server.kill()


@pytest.fixture(scope="module")
def tools_list(mcp_client):
    """Fetch and cache the tools/list response for the module."""
    resp = mcp_client.request("tools/list")
    if resp and "result" in resp:
        return resp["result"].get("tools", [])
    return []


# ============================================================
# Initialize / session
# ============================================================


def test_session_id_received(mcp_client):
    assert mcp_client.session_id is not None, "no mcp-session-id header received"


# ============================================================
# tools/list
# ============================================================


def test_tools_list_returns_response(mcp_client):
    resp = mcp_client.request("tools/list")
    assert resp is not None


def test_tools_list_has_6_tools(tools_list):
    assert len(tools_list) == 6, f"expected 6 tools, got {len(tools_list)}"


def test_tools_list_correct_names(tools_list):
    expected = {
        "get_london_score",
        "get_borough_health",
        "compare_boroughs",
        "get_trend",
        "run_sql",
        "search_scores",
    }
    actual = {t["name"] for t in tools_list}
    assert actual == expected, f"tool names mismatch: got {actual}"


@pytest.mark.parametrize("tool_name", [
    "get_london_score",
    "get_borough_health",
    "compare_boroughs",
    "get_trend",
    "run_sql",
    "search_scores",
])
def test_tool_does_not_expose_con_parameter(tools_list, tool_name):
    tool = next((t for t in tools_list if t["name"] == tool_name), None)
    assert tool is not None, f"tool {tool_name} not found in tools/list"
    props = tool.get("inputSchema", {}).get("properties", {})
    assert "con" not in props, f"{tool_name} exposes 'con' parameter"


# ============================================================
# get_london_score
# ============================================================


def test_get_london_score_returns_response(mcp_client):
    resp = mcp_client.request("tools/call", {"name": "get_london_score", "arguments": {}})
    assert resp is not None


def test_get_london_score_has_composite_score(mcp_client):
    resp = mcp_client.request("tools/call", {"name": "get_london_score", "arguments": {}})
    assert resp and "result" in resp
    content = resp["result"].get("content", [])
    assert content
    data = json.loads(content[0].get("text", "{}"))
    assert "composite_score" in data


def test_get_london_score_has_borough_count(mcp_client):
    resp = mcp_client.request("tools/call", {"name": "get_london_score", "arguments": {}})
    assert resp and "result" in resp
    content = resp["result"].get("content", [])
    assert content
    data = json.loads(content[0].get("text", "{}"))
    assert "borough_count" in data


def test_get_london_score_composite_in_range(mcp_client):
    resp = mcp_client.request("tools/call", {"name": "get_london_score", "arguments": {}})
    assert resp and "result" in resp
    content = resp["result"].get("content", [])
    assert content
    data = json.loads(content[0].get("text", "{}"))
    cs = data.get("composite_score")
    assert isinstance(cs, (int, float)) and 0 <= cs <= 100, f"composite_score: {cs}"


# ============================================================
# get_borough_health — Camden
# ============================================================


def test_get_borough_health_returns_response(mcp_client):
    resp = mcp_client.request("tools/call", {
        "name": "get_borough_health",
        "arguments": {"borough": "Camden"},
    })
    assert resp is not None


def test_get_borough_health_found_true(mcp_client):
    resp = mcp_client.request("tools/call", {
        "name": "get_borough_health",
        "arguments": {"borough": "Camden"},
    })
    assert resp and "result" in resp
    content = resp["result"].get("content", [])
    assert content
    data = json.loads(content[0].get("text", "{}"))
    assert data.get("found") is True


def test_get_borough_health_correct_code(mcp_client):
    resp = mcp_client.request("tools/call", {
        "name": "get_borough_health",
        "arguments": {"borough": "Camden"},
    })
    assert resp and "result" in resp
    content = resp["result"].get("content", [])
    assert content
    data = json.loads(content[0].get("text", "{}"))
    assert data.get("borough_code") == "E09000007"


def test_get_borough_health_has_composite_score(mcp_client):
    resp = mcp_client.request("tools/call", {
        "name": "get_borough_health",
        "arguments": {"borough": "Camden"},
    })
    assert resp and "result" in resp
    content = resp["result"].get("content", [])
    assert content
    data = json.loads(content[0].get("text", "{}"))
    assert "composite_score" in data


# ============================================================
# compare_boroughs
# ============================================================


def test_compare_boroughs_returns_response(mcp_client):
    resp = mcp_client.request("tools/call", {
        "name": "compare_boroughs",
        "arguments": {"metric": "composite_score", "top_n": 3},
    })
    assert resp is not None


def test_compare_boroughs_has_boroughs_array(mcp_client):
    resp = mcp_client.request("tools/call", {
        "name": "compare_boroughs",
        "arguments": {"metric": "composite_score", "top_n": 3},
    })
    assert resp and "result" in resp
    content = resp["result"].get("content", [])
    assert content
    data = json.loads(content[0].get("text", "{}"))
    assert isinstance(data.get("boroughs"), list)


def test_compare_boroughs_top_n_respected(mcp_client):
    resp = mcp_client.request("tools/call", {
        "name": "compare_boroughs",
        "arguments": {"metric": "composite_score", "top_n": 3},
    })
    assert resp and "result" in resp
    content = resp["result"].get("content", [])
    assert content
    data = json.loads(content[0].get("text", "{}"))
    boroughs = data.get("boroughs", [])
    assert len(boroughs) == 3, f"expected 3, got {len(boroughs)}"


def test_compare_boroughs_first_rank_is_1(mcp_client):
    resp = mcp_client.request("tools/call", {
        "name": "compare_boroughs",
        "arguments": {"metric": "composite_score", "top_n": 3},
    })
    assert resp and "result" in resp
    content = resp["result"].get("content", [])
    assert content
    data = json.loads(content[0].get("text", "{}"))
    boroughs = data.get("boroughs", [])
    assert boroughs and boroughs[0].get("rank") == 1


def test_compare_boroughs_first_has_borough_code(mcp_client):
    resp = mcp_client.request("tools/call", {
        "name": "compare_boroughs",
        "arguments": {"metric": "composite_score", "top_n": 3},
    })
    assert resp and "result" in resp
    content = resp["result"].get("content", [])
    assert content
    data = json.loads(content[0].get("text", "{}"))
    boroughs = data.get("boroughs", [])
    assert boroughs and "borough_code" in boroughs[0]


# ============================================================
# get_trend
# ============================================================


def test_get_trend_returns_response(mcp_client):
    resp = mcp_client.request("tools/call", {
        "name": "get_trend",
        "arguments": {"borough": "Camden", "metric": "composite_score", "days": 7},
    })
    assert resp is not None


def test_get_trend_found_true(mcp_client):
    resp = mcp_client.request("tools/call", {
        "name": "get_trend",
        "arguments": {"borough": "Camden", "metric": "composite_score", "days": 7},
    })
    assert resp and "result" in resp
    content = resp["result"].get("content", [])
    assert content
    data = json.loads(content[0].get("text", "{}"))
    assert data.get("found") is True


def test_get_trend_has_direction(mcp_client):
    resp = mcp_client.request("tools/call", {
        "name": "get_trend",
        "arguments": {"borough": "Camden", "metric": "composite_score", "days": 7},
    })
    assert resp and "result" in resp
    content = resp["result"].get("content", [])
    assert content
    data = json.loads(content[0].get("text", "{}"))
    assert "direction" in data


def test_get_trend_has_trend_array(mcp_client):
    resp = mcp_client.request("tools/call", {
        "name": "get_trend",
        "arguments": {"borough": "Camden", "metric": "composite_score", "days": 7},
    })
    assert resp and "result" in resp
    content = resp["result"].get("content", [])
    assert content
    data = json.loads(content[0].get("text", "{}"))
    assert isinstance(data.get("trend"), list)


# ============================================================
# run_sql — valid query
# ============================================================


def test_run_sql_valid_returns_response(mcp_client):
    resp = mcp_client.request("tools/call", {
        "name": "run_sql",
        "arguments": {"query": "SELECT COUNT(*) AS cnt FROM gold_scores"},
    })
    assert resp is not None


def test_run_sql_valid_success_true(mcp_client):
    resp = mcp_client.request("tools/call", {
        "name": "run_sql",
        "arguments": {"query": "SELECT COUNT(*) AS cnt FROM gold_scores"},
    })
    assert resp and "result" in resp
    content = resp["result"].get("content", [])
    assert content
    data = json.loads(content[0].get("text", "{}"))
    assert data.get("success") is True


def test_run_sql_valid_has_rows(mcp_client):
    resp = mcp_client.request("tools/call", {
        "name": "run_sql",
        "arguments": {"query": "SELECT COUNT(*) AS cnt FROM gold_scores"},
    })
    assert resp and "result" in resp
    content = resp["result"].get("content", [])
    assert content
    data = json.loads(content[0].get("text", "{}"))
    assert isinstance(data.get("rows"), list)


# ============================================================
# run_sql — blocked INSERT
# ============================================================


def test_run_sql_blocked_returns_response(mcp_client):
    resp = mcp_client.request("tools/call", {
        "name": "run_sql",
        "arguments": {"query": "INSERT INTO gold_scores VALUES (1)"},
    })
    assert resp is not None


def test_run_sql_blocked_success_false(mcp_client):
    resp = mcp_client.request("tools/call", {
        "name": "run_sql",
        "arguments": {"query": "INSERT INTO gold_scores VALUES (1)"},
    })
    assert resp and "result" in resp
    content = resp["result"].get("content", [])
    assert content
    data = json.loads(content[0].get("text", "{}"))
    assert data.get("success") is False


def test_run_sql_blocked_has_error(mcp_client):
    resp = mcp_client.request("tools/call", {
        "name": "run_sql",
        "arguments": {"query": "INSERT INTO gold_scores VALUES (1)"},
    })
    assert resp and "result" in resp
    content = resp["result"].get("content", [])
    assert content
    data = json.loads(content[0].get("text", "{}"))
    assert "error" in data


# ============================================================
# search_scores
# ============================================================


def test_search_scores_returns_response(mcp_client):
    resp = mcp_client.request("tools/call", {
        "name": "search_scores",
        "arguments": {"query": "worst air quality", "n_results": 3},
    })
    assert resp is not None


def test_search_scores_has_results_array(mcp_client):
    resp = mcp_client.request("tools/call", {
        "name": "search_scores",
        "arguments": {"query": "worst air quality", "n_results": 3},
    })
    assert resp and "result" in resp
    content = resp["result"].get("content", [])
    assert content
    data = json.loads(content[0].get("text", "{}"))
    assert isinstance(data.get("results"), list)


def test_search_scores_has_count(mcp_client):
    resp = mcp_client.request("tools/call", {
        "name": "search_scores",
        "arguments": {"query": "worst air quality", "n_results": 3},
    })
    assert resp and "result" in resp
    content = resp["result"].get("content", [])
    assert content
    data = json.loads(content[0].get("text", "{}"))
    assert "count" in data
