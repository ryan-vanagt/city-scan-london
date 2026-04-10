"""
Shared HTTP retry utility for ingestion sources.

Provides exponential backoff with 429 rate-limit handling (reads Retry-After
header, sleeps capped to 120 seconds). Re-raises the last exception after all
attempts are exhausted.
"""

import logging
import time
from collections.abc import Callable
from typing import Any

import requests

logger = logging.getLogger(__name__)

_MAX_RETRY_AFTER = 120  # seconds — never sleep more than this for a 429


def retry_request(
    func: Callable[..., requests.Response],
    *args: Any,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    **kwargs: Any,
) -> requests.Response:
    """Call func(*args, **kwargs) with exponential backoff on failure.

    Handles HTTP 429 responses specially: reads the Retry-After header and
    sleeps that duration (capped to _MAX_RETRY_AFTER) before retrying.

    For all other transient failures (network errors, timeouts) the sleep
    between attempts is base_delay * 2^attempt.

    The response is returned as-is after a successful call — callers should
    still call raise_for_status() on non-429 HTTP errors (or this function
    will re-raise them on the final attempt).

    Args:
        func: Callable that performs the HTTP request and returns a
              requests.Response (e.g. requests.get or requests.post).
        *args: Positional arguments forwarded to func.
        max_attempts: Maximum number of attempts (default 3).
        base_delay: Base delay in seconds for exponential backoff (default 1.0).
        **kwargs: Keyword arguments forwarded to func.

    Returns:
        requests.Response from the first successful (non-429) call.

    Raises:
        requests.RequestException: After all attempts are exhausted.
    """
    last_exc: Exception | None = None

    for attempt in range(max_attempts):
        try:
            response = func(*args, **kwargs)

            # Handle rate limiting explicitly before raise_for_status
            if response.status_code == 429:
                raw_header = response.headers.get("Retry-After", "")
                try:
                    retry_after = int(raw_header)
                except (ValueError, TypeError):
                    retry_after = int(base_delay * (2 ** attempt)) + 10
                sleep_secs = min(retry_after, _MAX_RETRY_AFTER)
                logger.warning(
                    "HTTP 429 rate-limited — sleeping %ds before retry (attempt %d/%d)",
                    sleep_secs, attempt + 1, max_attempts,
                )
                time.sleep(sleep_secs)
                # 429 is always retried — treat as a transient error
                last_exc = requests.HTTPError(
                    f"429 Too Many Requests (attempt {attempt + 1}/{max_attempts})",
                    response=response,
                )
                continue

            return response

        except requests.RequestException as exc:
            last_exc = exc
            if attempt < max_attempts - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "Request failed (attempt %d/%d): %s — retrying in %.1fs",
                    attempt + 1, max_attempts, exc, delay,
                )
                time.sleep(delay)
            else:
                logger.error(
                    "Request failed after %d attempts: %s",
                    max_attempts, exc,
                )

    raise last_exc  # type: ignore[misc]
