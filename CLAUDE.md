# CLAUDE.md — CityScan London

This file provides context for AI coding assistants (Cursor, Claude Code) working on this project.

---

## What this project is

CityScan models London as a human body using live data. Four public data sources map to four biological systems and produce a real-time health score per London borough, queryable via a natural language agent interface. It is a UCL MSc Data Engineering assignment (MSIN0166) and a portfolio project.

- 🫁 **Lungs** → OpenAQ (air quality)
- 🩸 **Arteries** → TfL API (transport disruption)
- 🧠 **Brain** → Reddit + Guardian API (public sentiment)
- 🛡️ **Immune system** → Met Police API (crime)

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
| LLM | Anthropic claude-haiku-4-5 via `anthropic` SDK |
| Sentiment model | `cardiffnlp/twitter-roberta-base-sentiment` (local, CPU) |
| API | FastAPI + Uvicorn |
| Frontend | Next.js (React) |
| Containerisation | Docker + Docker Compose |
| Package management | pip + `requirements.txt` per service |

---

## Architecture — three-layer pipeline

```
Bronze (raw JSON) → Silver (DuckDB, normalised) → Gold (DuckDB, scored + ChromaDB, embedded)
```

- **Bronze:** raw timestamped API responses, one folder per source under `/data/bronze/`
- **Silver:** all sources normalised to `(borough_code, borough_name, timestamp, metric_name, raw_value, normalised_score, source)` in DuckDB
- **Gold:** one row per borough per cycle `(borough_code, borough_name, timestamp, air_score, transit_score, sentiment_score, crime_score, composite_score)` in DuckDB; same rows embedded as text in ChromaDB for RAG
- Borough codes follow ONS GLA boundary codes — lookup in `/pipeline/schemas.py`
- Scores are always 0–100, where 100 = healthiest

---

## Agents

### Doctor Agent (`/agents/doctor.py`)
- LangGraph ReAct agent
- Answers natural language queries using ChromaDB RAG + DuckDB tool calls
- Tools: `get_borough_health`, `get_london_score`, `get_trend`, `compare_boroughs`
- LLM: claude-haiku-4-5
- Only Gold-layer aggregated data reaches the LLM — no raw post text, no PII

### Bulletin Agent (`/agents/bulletin.py`)
- LangChain prompt chain (not a ReAct loop)
- Triggered by APScheduler (daily) and `POST /bulletin/generate`
- Chain: fetch scores → query trends → fetch Guardian headlines → synthesise → store as markdown
- Output saved to `/data/bulletins/YYYY-MM-DD.md`

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
```

Load with `python-dotenv` in every service entry point.

---

## Key commands

```bash
# Run everything
docker compose up

# Run ingestion only (dev)
cd ingestion && python scheduler.py

# Run API only (dev)
cd api && uvicorn main:app --reload --port 8000

# Run frontend only (dev)
cd frontend && npm run dev

# Trigger pipeline manually (dev)
python pipeline/bronze.py
python pipeline/silver.py
python pipeline/gold.py
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
POST /agent/query               — Doctor agent (body: {question: string})
GET  /bulletin/latest           — latest bulletin markdown
POST /bulletin/generate         — trigger bulletin generation
```

All responses are JSON. Scores always 0–100.

---

## Docker services

| Service | Dockerfile | Port |
|---|---|---|
| `api` | `docker/Dockerfile.api` | 8000 |
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

---

## What NOT to do

- Do not store raw Reddit post text or Guardian article body anywhere on disk
- Do not send raw post text or user-identifiable data to the Anthropic API
- Do not commit `.env` or any file containing API keys
- Do not use `print` for logging — use `logging.getLogger(__name__)`
- Do not hardcode borough names as dictionary keys — use ONS codes
- Do not create new DuckDB connections inside loops — reuse a module-level connection
- Do not run the sentiment model inside the API request cycle — it runs in the ingestion service only

---

## Out of scope (do not build)

- User authentication or accounts
- Cloud deployment (local Docker only for now)
- Forecasting / predictive layer (leave room for it architecturally but don't build it)
- Real-time websocket streaming
- Any database other than DuckDB + ChromaDB
