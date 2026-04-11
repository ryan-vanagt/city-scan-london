"""
CityScan FastAPI application entry point.

Mounts all routers and configures CORS for the Next.js frontend.
All health scores returned are in the range 0-100 (100 = healthiest).
"""

import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agents.logging_db import ensure_agent_logs_table, ensure_bulletin_logs_table
from api.db import close_connection, open_connection
from api.routers import agent, boroughs, health

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open DuckDB on startup, close on shutdown."""
    load_dotenv()
    ensure_agent_logs_table()
    ensure_bulletin_logs_table()
    open_connection()
    yield
    close_connection()


app = FastAPI(
    title="CityScan London",
    description="London health scores from live public data — air quality, transit, sentiment, crime & A&E.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(boroughs.router)
app.include_router(agent.router)
