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
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agents.bulletin import generate_bulletin
from agents.doctor import stream_doctor_response

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agent"])

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BULLETINS_DIR = PROJECT_ROOT / "data" / "bulletins"

# SSE stream timeout in seconds
_SSE_TIMEOUT_SECONDS = 60

# Rate limiting for bulletin generation (seconds between requests)
_BULLETIN_COOLDOWN_SECONDS = 60
_last_bulletin_time: float = 0


class AgentQuery(BaseModel):
    """Request body for the Doctor Agent endpoint."""

    question: str = Field(..., min_length=1, max_length=500)


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
    try:
        return StreamingResponse(
            _guarded_sse_stream(body.question, request),
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
    return {"date": date_str, "content": content}


@router.post("/bulletin/generate")
async def bulletin_generate():
    """Trigger on-demand bulletin generation."""
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
