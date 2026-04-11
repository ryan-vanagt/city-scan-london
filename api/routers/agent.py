"""
Agent and bulletin endpoints.

POST /agent/query        — Doctor agent query; returns SSE stream (text/event-stream)
                           body: {"question": string}
                           events: token stream -> final [SOURCES] JSON event

GET  /bulletin/latest    — latest generated bulletin as markdown
POST /bulletin/generate  — trigger on-demand bulletin generation
"""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agents.doctor import stream_doctor_response

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agent"])

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BULLETINS_DIR = PROJECT_ROOT / "data" / "bulletins"


class AgentQuery(BaseModel):
    """Request body for the Doctor Agent endpoint."""

    question: str = Field(..., min_length=1, max_length=500)


@router.post("/agent/query")
async def agent_query(body: AgentQuery):
    """Stream a Doctor Agent response as Server-Sent Events."""
    try:
        return StreamingResponse(
            stream_doctor_response(body.question),
            media_type="text/event-stream",
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


@router.post("/bulletin/generate", status_code=501)
async def bulletin_generate():
    """Trigger bulletin generation (not yet implemented)."""
    raise HTTPException(status_code=501, detail="Bulletin generation not yet implemented")
