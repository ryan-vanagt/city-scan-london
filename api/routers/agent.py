"""
Agent and bulletin endpoints.

POST /agent/query        — Doctor agent query; returns SSE stream (text/event-stream)
                           body: {"question": string}
                           events: token stream -> final [SOURCES] JSON event

GET  /bulletin/latest    — latest generated bulletin as markdown
POST /bulletin/generate  — trigger on-demand bulletin generation
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agents.bulletin import generate_bulletin
from agents.doctor import stream_doctor_response
from api.rate_limit import check_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agent"])

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BULLETINS_DIR = PROJECT_ROOT / "data" / "bulletins"

# SSE stream timeout in seconds
_SSE_TIMEOUT_SECONDS = 180  # 180s to support Sonnet/Opus (more tool calls = longer)

# Rate limiting for bulletin generation (seconds between requests)
_BULLETIN_COOLDOWN_SECONDS = 60
_last_bulletin_time: float = 0


_DOCTOR_ACCESS_CODE = os.environ.get("DOCTOR_ACCESS_CODE", "")
if not _DOCTOR_ACCESS_CODE:
    logger.warning(
        "DOCTOR_ACCESS_CODE is unset — /agent/query and /bulletin/generate "
        "will refuse all callers. Set DOCTOR_ACCESS_CODE to open the endpoints."
    )


def _client_ip(request: Request) -> str:
    """Rate-limit key: use the real TCP peer, not X-Forwarded-For.

    XFF is trivially spoofed when we are not behind a trusted reverse proxy.
    The live deployment binds uvicorn directly to 0.0.0.0:8000, so the only
    trustworthy client identifier is the TCP peer address. Revisit this if
    we ever add a reverse proxy — at that point we must explicitly parse
    XFF and trust only the upstream hop.
    """
    if request.client:
        return request.client.host
    return "unknown"


class AgentQuery(BaseModel):
    """Request body for the Doctor Agent endpoint."""

    question: str = Field(..., min_length=1, max_length=500)
    role: str | None = Field(
        None,
        pattern=r"^(policy|public)$",
        description="Optional role context: policy or public",
    )
    access_code: str | None = Field(None, description="Access code for Doctor consultations")


async def _guarded_sse_stream(question: str, request: Request):
    """Wrap the Doctor Agent SSE stream with disconnect detection and timeout."""
    start = time.monotonic()
    try:
        async for chunk in stream_doctor_response(question):
            # Check if client disconnected
            if await request.is_disconnected():
                logger.info("SSE client disconnected, stopping stream")
                return
            # Check overall timeout
            if time.monotonic() - start > _SSE_TIMEOUT_SECONDS:
                logger.warning("SSE stream timed out after %ds", _SSE_TIMEOUT_SECONDS)
                err = json.dumps({"type": "error", "message": "Stream timed out"})
                yield f"data: {err}\n\n"
                yield "data: [DONE]\n\n"
                return
            yield chunk
    except asyncio.CancelledError:
        logger.info("SSE stream cancelled for query: %s", question[:100])
        return


@router.post("/agent/query")
async def agent_query(body: AgentQuery, request: Request):
    """Stream a Doctor Agent response as Server-Sent Events."""
    # Fail closed when access code is unset, and reject any mismatch.
    if not _DOCTOR_ACCESS_CODE or body.access_code != _DOCTOR_ACCESS_CODE:
        raise HTTPException(status_code=403, detail="Invalid access code. The Doctor requires an access code for consultations.")

    # Rate limiting (per-IP + global daily cap) keyed on real TCP peer.
    client_ip = _client_ip(request)
    limit_msg = check_rate_limit(client_ip)
    if limit_msg:
        raise HTTPException(status_code=429, detail=limit_msg)

    # Prepend role context if provided
    question = body.question
    if body.role:
        question = f"[Role: {body.role}] {question}"

    try:
        return StreamingResponse(
            _guarded_sse_stream(question, request),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    except Exception as exc:
        logger.error("Doctor Agent initialization failed: %s", exc)
        raise HTTPException(status_code=503, detail="Doctor Agent unavailable") from exc


@router.get("/bulletin/latest")
async def bulletin_latest():
    """Return the most recently generated bulletin as JSON."""
    if not BULLETINS_DIR.exists():
        raise HTTPException(status_code=404, detail="No bulletins generated yet")

    md_files = sorted(BULLETINS_DIR.glob("*.md"), reverse=True)
    if not md_files:
        raise HTTPException(status_code=404, detail="No bulletins generated yet")

    latest = md_files[0]
    date_str = latest.stem  # e.g. "2026-04-11"
    content = latest.read_text(encoding="utf-8")

    # Load companion scores JSON if available (generated alongside .md)
    scores = None
    json_path = latest.with_suffix(".json")
    try:
        if json_path.exists():
            scores = json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.debug("Could not load bulletin scores sidecar: %s", json_path)

    result: dict = {"date": date_str, "content": content}
    if scores is not None:
        result["scores"] = scores
    return result


@router.post("/bulletin/generate")
async def bulletin_generate(request: Request):
    """Trigger on-demand bulletin generation.

    Each call invokes an LLM (Claude Haiku) and incurs API cost. Protected
    by DOCTOR_ACCESS_CODE (mandatory — refuses all callers when unset) plus
    the per-IP rate limiter used by the Doctor endpoint, plus a 60s global
    cooldown.
    """
    body: dict = {}
    if request.headers.get("content-type", "").startswith("application/json"):
        try:
            raw = await request.body()
            if raw:
                body = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = {}
    if not _DOCTOR_ACCESS_CODE or body.get("access_code") != _DOCTOR_ACCESS_CODE:
        raise HTTPException(status_code=403, detail="Access code required for bulletin generation")

    # Per-IP rate limit so distributed callers can't hammer the module-global cooldown.
    client_ip = _client_ip(request)
    limit_msg = check_rate_limit(client_ip)
    if limit_msg:
        raise HTTPException(status_code=429, detail=limit_msg)

    global _last_bulletin_time
    now = time.time()
    if now - _last_bulletin_time < _BULLETIN_COOLDOWN_SECONDS:
        raise HTTPException(
            status_code=429,
            detail=f"Bulletin generation rate limited — wait {_BULLETIN_COOLDOWN_SECONDS}s between requests",
        )

    try:
        result = generate_bulletin(trigger="manual")
    except Exception as exc:
        logger.error("Bulletin generation failed: %s", exc)
        raise HTTPException(status_code=503, detail="Bulletin generation failed") from exc

    if "error" in result:
        raise HTTPException(status_code=503, detail=result["error"])

    _last_bulletin_time = time.time()

    return {
        "date": result["date"],
        "content": result["content"],
        "sources": result.get("sources"),
    }
