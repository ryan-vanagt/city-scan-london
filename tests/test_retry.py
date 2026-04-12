"""Test ingestion/retry.py — exponential backoff and 429 handling."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from ingestion.retry import retry_request


def _make_response(status_code: int, headers: dict | None = None) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.headers = headers or {}
    return resp


def test_retry_returns_on_first_success():
    mock_func = MagicMock(return_value=_make_response(200))
    result = retry_request(mock_func, "https://example.com")
    assert result.status_code == 200
    assert mock_func.call_count == 1


def test_retry_retries_on_429():
    responses = [
        _make_response(429, {"Retry-After": "1"}),
        _make_response(200),
    ]
    mock_func = MagicMock(side_effect=responses)
    with patch("ingestion.retry.time.sleep"):
        result = retry_request(mock_func, "https://example.com", max_attempts=3)
    assert result.status_code == 200
    assert mock_func.call_count == 2


def test_retry_raises_after_max_attempts():
    mock_func = MagicMock(side_effect=requests.ConnectionError("timeout"))
    with patch("ingestion.retry.time.sleep"):
        with pytest.raises(requests.ConnectionError):
            retry_request(mock_func, "https://example.com", max_attempts=3)
    assert mock_func.call_count == 3


def test_retry_respects_retry_after_header():
    responses = [
        _make_response(429, {"Retry-After": "5"}),
        _make_response(200),
    ]
    mock_func = MagicMock(side_effect=responses)
    with patch("ingestion.retry.time.sleep") as mock_sleep:
        retry_request(mock_func, "https://example.com", max_attempts=3)
    # First sleep should respect the Retry-After header (capped at 120)
    mock_sleep.assert_called_once()
    assert mock_sleep.call_args[0][0] == 5


def test_retry_caps_retry_after_at_max():
    responses = [
        _make_response(429, {"Retry-After": "999"}),
        _make_response(200),
    ]
    mock_func = MagicMock(side_effect=responses)
    with patch("ingestion.retry.time.sleep") as mock_sleep:
        retry_request(mock_func, "https://example.com", max_attempts=3)
    mock_sleep.assert_called_once()
    assert mock_sleep.call_args[0][0] == 120  # _MAX_RETRY_AFTER
