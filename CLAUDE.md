# CLAUDE.md — CityScan London

This file provides context for AI coding assistants (Claude Code) working on this project. Update it as each component is built to reflect what was actually implemented.

---

## What this project is

CityScan models London as a human body using live data. Four public data sources map to four biological systems and produce a real-time health score per London borough, queryable via a natural language agent interface and summarised in a daily LLM-generated bulletin.

- 🫁 **Lungs** → OpenAQ (air quality)
- 🩸 **Arteries** → TfL API (transport disruption)
- 🧠 **Brain** → Reddit + Guardian API (public sentiment)
- 🛡️ **Immune system** → Met Police API (crime)

Dual purpose: UCL MSc Data Engineering assignment (MSIN0166) + public portfolio project.

Full product spec in `PRD.md`.

---

## Tech stack

| Layer | Technology |
|---|---|
| Language | Python 3.11 |
| Scheduling | APScheduler |
| Structured storage | DuckDB |
| Vector storage | ChromaDB |
| Agent framework | LangChain + LangGraph |
| LLM | `claude-haiku-4-5` via `anthropic` SDK |
| Sentiment model | `cardiffnlp/twitter-roberta-base-sentiment` (local, CPU) |
| MCP server | `mcp` Python SDK |
| API | FastAPI + Uvicorn |
| Frontend | Next.js (React) — portfolio-facing, chat UI for Doctor agent |
| Containerisation | Docker + Docker Compose |
| Package management | pip + `requirements.txt` per service |

---

## Architecture — three-layer pipeline

```
Bronze (raw JSON) → Silver (DuckDB, normalised) → Gold (DuckDB, scored + ChromaDB, embedded)
```

- **Bronze:** raw timestamped API responses, one folder per source under `/data/bronze/`
- **Silver:** all sources normalised to `(borough_code, borough_name, timestamp, metric_name, raw_value, normalised_score, source, ingested_at, pipeline_stage)` in DuckDB
- **Gold:** one row per borough per cycle `(borough_code, borough_name, timestamp, air_score, transit_score, sentiment_score, crime_score, composite_score, ingested_at, pipeline_stage)` in DuckDB; same rows embedded as text in ChromaDB for RAG
- Borough codes follow ONS GLA boundary codes — lookup in `/pipeline/schemas.py`
- Scores are always 0–100, where 100 = healthiest

### Pipeline execution model

The `ingestion` service owns the full pipeline. There is no separate pipeline Docker container. APScheduler runs the complete chain on each tick:

```
fetch() → bronze.save() → silver.transform() → gold.aggregate() → chromadb.embed()
```

The `pipeline/` directory contains transformation logic as importable functions called by the scheduler. A manual one-shot trigger exists for development at `ingestion/run_pipeline.py`.

---

## Agents

### Doctor Agent (`/agents/doctor.py`)
- LangGraph ReAct agent
- Answers natural language queries using ChromaDB RAG + DuckDB tool calls
- Tools: `get_borough_health`, `get_london_score`, `get_trend`, `compare_boroughs`
- LLM: `claude-haiku-4-5`
- Only Gold-layer aggregated data reaches the LLM — no raw post text, no PII
- **Output schema:**
  ```json
  {
    "answer": "streaming text...",
    "sources": [
      {"type": "duckdb", "tool": "get_borough_health", "data": {...}},
      {"type": "guardian", "headline": "...", "url": "..."}
    ]
  }
  ```
- `answer` is streamed token-by-token via SSE; `sources` is flushed as a final SSE event
- Every tool output is logged to `agent_logs` in DuckDB for audit

### Bulletin Agent (`/agents/bulletin.py`)
- LangChain prompt chain (not a ReAct loop)
- Triggered by APScheduler (daily) and `POST /bulletin/generate`
- Chain: fetch scores from DuckDB → query trends from DuckDB → fetch Guardian headlines → synthesise → store as markdown
- Does **not** call the Doctor agent — uses direct DuckDB queries for reliability
- Output saved to `/data/bulletins/YYYY-MM-DD.md`
- Every run logged to `bulletin_logs` in DuckDB

---

## Agent Evaluation & Observability

### agent_logs (DuckDB)
Captures every Doctor agent interaction. Schema:
```sql
id TEXT, timestamp TEXT, query TEXT,
tools_called TEXT,   -- JSON array
tool_inputs TEXT,    -- JSON
tool_outputs TEXT,   -- JSON (raw DuckDB results — audit against final_response)
sources_cited TEXT,  -- JSON (what was returned to user)
final_response TEXT,
latency_ms INTEGER,
model_used TEXT
```

### bulletin_logs (DuckDB)
```sql
id TEXT, timestamp TEXT, trigger TEXT,
scores_used TEXT,      -- JSON snapshot of Gold scores at generation time
headlines_used TEXT,   -- JSON array
output_path TEXT,
latency_ms INTEGER
```

---

## MCP Server (`/mcp_server/server.py`)

Exposes the four Doctor agent tools as an MCP (Model Context Protocol) server so any MCP-compatible client (Claude Desktop, other agents) can query CityScan directly.

- SDK: `mcp` Python package
- Port: 8002
- Tools: `get_borough_health`, `get_london_score`, `get_trend`, `compare_boroughs`
- Same tool functions as used by the Doctor agent — no duplication

---

## Sentiment scoring

Raw Reddit post text and Guardian trailText are scored locally before entering the pipeline:
- Model: `cardiffnlp/twitter-roberta-base-sentiment`
- Returns a float in [-1, 1] which is normalised to 0–100 for Silver layer
- Raw text is **never** written to disk or sent to any external API
- Scorer lives in `/sentiment/scorer.py`

---

## Environment variables

Never commit `.env`. Use `.env.example` as template.

```
ANTHROPIC_API_KEY=
OPENAQ_API_KEY=
GUARDIAN_API_KEY=
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USER_AGENT=cityscan/1.0
TFL_APP_KEY=
SCORE_WEIGHTS=0.25,0.25,0.25,0.25
```

Load with `python-dotenv` in every service entry point.

---

## Key commands

```bash
# Run everything
docker compose up

# Run one full pipeline cycle manually (dev)
python ingestion/run_pipeline.py

# Run API only (dev)
cd api && uvicorn main:app --reload --port 8000

# Run MCP server only (dev)
cd mcp_server && python server.py

# Run frontend only (dev)
cd frontend && npm run dev

# Run ingestion scheduler only (dev)
cd ingestion && python scheduler.py
```

---

## Data sources — API notes

**OpenAQ** (`/ingestion/sources/openaq.py`)
- Endpoint: `https://api.openaq.org/v3/locations?country=GB&city=London`
- Parameters: filter by `parameter` (pm25, no2, o3), group by borough approximation using coordinates
- No borough field natively — map station coordinates to borough using a bounding box lookup

**TfL** (`/ingestion/sources/tfl.py`)
- Endpoint: `https://api.tfl.gov.uk/line/mode/tube,bus,dlr,overground/disruption`
- Also: `https://api.tfl.gov.uk/StopPoint/{id}/Crowding/{dayOfWeek}` for crowding
- App key passed as query param `?app_key=`
- No borough field — aggregate by line and map lines to borough coverage zones

**Reddit** (`/ingestion/sources/reddit.py`)
- Use PRAW library
- Subreddits: `r/london`, `r/londonuk`, `r/ukpolitics` (filter for London mentions)
- Fetch top 50 hot posts per cycle
- Score each post title + body locally before storing anything

**Guardian** (`/ingestion/sources/guardian.py`)
- Endpoint: `https://content.guardianapis.com/search`
- Params: `q=london&tag=uk/london&show-fields=headline,trailText&page-size=20&order-by=newest`
- Store: headline, trailText (for sentiment), webUrl (for citation)
- Never store full article body

**Met Police** (`/ingestion/sources/met_police.py`)
- Endpoint: `https://data.police.uk/api/crimes-street/all-crime?lat={lat}&lng={lng}&date={YYYY-MM}`
- Data is ~2 months old — treat as static monthly enrichment
- Loop through borough centroids to gather per-borough crime counts

---

## FastAPI — route structure

```
GET  /health                    — service check
GET  /london/score              — overall London health score
GET  /boroughs                  — all boroughs with scores
GET  /borough/{name}            — single borough breakdown
GET  /borough/{name}/trend      — 7-day trend
POST /agent/query               — Doctor agent, SSE stream (text/event-stream)
                                  body: {question: string}
                                  events: token stream → final [SOURCES] event
GET  /bulletin/latest           — latest bulletin markdown
POST /bulletin/generate         — trigger bulletin generation
```

All non-streaming responses are JSON. Scores always 0–100.

---

## Docker services

| Service | Dockerfile | Port |
|---|---|---|
| `api` | `docker/Dockerfile.api` | 8000 |
| `mcp_server` | `docker/Dockerfile.mcp` | 8002 |
| `frontend` | `docker/Dockerfile.frontend` | 3000 |
| `ingestion` | `docker/Dockerfile.ingestion` | — |
| `chromadb` | official chromadb image | 8001 |

Services share a Docker volume for `/data/` and `/embeddings/`.

---

## Coding conventions

- Type hints on all function signatures
- Docstrings on all public functions
- Every source file has a module-level docstring explaining what it does
- Scores always validated to be in [0, 100] range before writing to Silver/Gold
- All API calls wrapped in try/except with logged errors — never silent failures
- Use `logging` module, not `print`
- Borough code is always the ONS 9-character code (e.g. `E09000001`) — never use borough name as a key
- Timestamps always UTC, stored as ISO 8601 strings
- DuckDB connections are module-level — never create a new connection inside a loop

---

## What NOT to do

- Do not store raw Reddit post text or Guardian article body anywhere on disk
- Do not send raw post text or user-identifiable data to the Anthropic API
- Do not commit `.env` or any file containing API keys
- Do not use `print` for logging — use `logging.getLogger(__name__)`
- Do not hardcode borough names as dictionary keys — use ONS codes
- Do not create new DuckDB connections inside loops — reuse a module-level connection
- Do not run the sentiment model inside the API request cycle — it runs in the ingestion service only
- Do not call the Doctor agent from inside the Bulletin agent — use direct DuckDB queries

---

## Out of scope (do not build)

- User authentication or accounts
- Cloud deployment (local Docker only)
- Forecasting / predictive layer (leave room for it architecturally but don't build it)
- Real-time WebSocket bidirectional streaming (SSE one-way is in scope)
- GraphRAG (noted as future enhancement — do not build now)
- Any database other than DuckDB + ChromaDB
