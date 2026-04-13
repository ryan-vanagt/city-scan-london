"""
Per-IP and global rate limiting for the Doctor Agent endpoint.

Uses in-memory counters that reset on a rolling window basis.
Designed for single-worker Uvicorn (module-level state).

Limits:
  - Per IP: AGENT_RATE_LIMIT_PER_IP_HOUR queries/hour,
            AGENT_RATE_LIMIT_PER_IP_DAY queries/day
  - Global: AGENT_RATE_LIMIT_GLOBAL_DAY queries/day across all users
"""

import logging
import os
import time
import threading
from collections import defaultdict

logger = logging.getLogger(__name__)

# Configurable via env vars (with sensible defaults)
AGENT_RATE_LIMIT_PER_IP_HOUR = int(os.environ.get("AGENT_RATE_LIMIT_PER_IP_HOUR", "15"))
AGENT_RATE_LIMIT_PER_IP_DAY = int(os.environ.get("AGENT_RATE_LIMIT_PER_IP_DAY", "40"))
AGENT_RATE_LIMIT_GLOBAL_DAY = int(os.environ.get("AGENT_RATE_LIMIT_GLOBAL_DAY", "150"))

_lock = threading.Lock()

# Per-IP tracking: {ip: [timestamp, timestamp, ...]}
_ip_requests: dict[str, list[float]] = defaultdict(list)

# Global daily tracking
_global_count: int = 0
_global_day_start: float = 0.0


_last_sweep: float = 0.0
_SWEEP_INTERVAL: float = 3600  # sweep all IPs every hour


def _cleanup_ip(ip: str, now: float) -> None:
    """Remove timestamps older than 24h for an IP."""
    cutoff = now - 86400
    _ip_requests[ip] = [t for t in _ip_requests[ip] if t > cutoff]


def _sweep_stale_ips(now: float) -> None:
    """Evict IPs with no requests in the last 24h. Runs at most once per hour."""
    global _last_sweep
    if now - _last_sweep < _SWEEP_INTERVAL:
        return
    _last_sweep = now
    cutoff = now - 86400
    stale = [ip for ip, ts in _ip_requests.items() if not ts or ts[-1] < cutoff]
    for ip in stale:
        del _ip_requests[ip]
    if stale:
        logger.debug("Rate limiter: swept %d stale IPs", len(stale))


def check_rate_limit(ip: str) -> str | None:
    """Check if a request from this IP is allowed.

    Returns None if allowed, or an error message string if rate-limited.
    """
    global _global_count, _global_day_start
    now = time.time()

    with _lock:
        # Reset global counter at midnight (rolling 24h window)
        if now - _global_day_start > 86400:
            _global_count = 0
            _global_day_start = now
            logger.info("Rate limiter: global daily counter reset")

        # Check global daily cap
        if _global_count >= AGENT_RATE_LIMIT_GLOBAL_DAY:
            logger.warning("Rate limiter: global daily cap reached (%d)", AGENT_RATE_LIMIT_GLOBAL_DAY)
            return f"Daily query limit reached ({AGENT_RATE_LIMIT_GLOBAL_DAY} queries/day). Try again tomorrow."

        # Periodic sweep of stale IPs to prevent unbounded memory growth
        _sweep_stale_ips(now)

        # Clean up old timestamps for this IP
        _cleanup_ip(ip, now)
        timestamps = _ip_requests[ip]

        # Check per-IP hourly limit
        one_hour_ago = now - 3600
        recent_hour = sum(1 for t in timestamps if t > one_hour_ago)
        if recent_hour >= AGENT_RATE_LIMIT_PER_IP_HOUR:
            logger.warning("Rate limiter: IP %s hit hourly cap (%d)", ip, AGENT_RATE_LIMIT_PER_IP_HOUR)
            return f"Rate limited — max {AGENT_RATE_LIMIT_PER_IP_HOUR} queries per hour. Try again later."

        # Check per-IP daily limit
        if len(timestamps) >= AGENT_RATE_LIMIT_PER_IP_DAY:
            logger.warning("Rate limiter: IP %s hit daily cap (%d)", ip, AGENT_RATE_LIMIT_PER_IP_DAY)
            return f"Daily limit reached — max {AGENT_RATE_LIMIT_PER_IP_DAY} queries per day."

        # Allowed — record the request
        timestamps.append(now)
        _global_count += 1

        return None
