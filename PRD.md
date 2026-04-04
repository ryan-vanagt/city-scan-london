# CityScan London — Product Requirements Document

## Overview

CityScan is a live urban health diagnostic platform that models London as a human body. Each data source maps to a biological system — air quality to lungs, transport to arteries, public sentiment to the brain, crime to the immune system. The system produces a real-time health score per London borough and an overall city health score, queryable via a natural language agent interface and summarised in a weekly LLM-generated bulletin.

**Tagline:** *A CT scan for the city.*

**Target users (enterprise framing):** Urban planners, city councils, emergency services, property analysts, public health researchers.

**GitHub repo:** `city-scan-london` (public)

**Assignment deadline:** 14 April 2026

**Module:** MSIN0166 — Data Engineering, UCL School of Management

---

## The Biological Metaphor

| Organ | Data Source | Signal | Update Cadence |
|---|---|---|---|
| 🫁 Lungs | OpenAQ API | PM2.5, NO2, O3 per borough | Hourly |
| 🩸 Arteries | TfL Unified API | Line disruptions, crowding index | Real-time |
| 🧠 Brain | Reddit (r/london, r/ukpolitics) + Guardian API | NLP sentiment score from posts & headlines | Every 3 hours |
| 🛡️ Immune System | Met Police API | Crime rate by category per borough | Monthly (static enrichment) |

Each signal is normalised to a 0–100 score (100 = healthy). The composite borough health score is a weighted average of all four signals. The overall London score aggregates all boroughs.

---

## System Architecture

### Data Tier — Bronze / Silver / Gold

**Bronze layer** — raw ingestion
- Raw API responses stored as timestamped JSON files
- One directory per source: `/data/bronze/openaq/`, `/data/bronze/tfl/`, `/data/bronze/reddit/`, `/data/bronze/guardian/`, `/data/bronze/met_police/`
- Nothing is transformed at this stage
- Ingestion runs on a schedule via APScheduler

**Silver layer** — cleaned & normalised
- All sources normalised to a common schema in DuckDB:
  `(borough_code, borough_name, timestamp, metric_name, raw_value, normalised_score, source)`
- Borough codes follow ONS Greater London Authority boundary codes (static lookup file)
- Reddit and Guardian raw text is processed locally by a sentiment model before entering Silver — raw post content never leaves the machine
- Sentiment model: `cardiffnlp/twitter-roberta-base-sentiment` (runs on CPU)

**Gold layer** — aggregated health scores
- One row per borough per ingestion cycle:
  `(borough_code, borough_name, timestamp, air_score, transit_score, sentiment_score, crime_score, composite_score)`
- Stored in DuckDB (structured) and embedded into ChromaDB (vector, for RAG)
- Composite score = weighted average: air (25%), transit (25%), sentiment (25%), crime (25%)
- Weights are configurable via environment variable

### Storage
- **DuckDB** — primary structured store for Silver and Gold layers
- **ChromaDB** — vector store for Gold-layer embeddings, enabling semantic RAG queries
- **Local filesystem** — Bronze JSON files, organised by source and date

### Data Lineage
- Each record carries a `source`, `ingested_at`, and `pipeline_stage` field through all three layers
- Transformations documented in code comments and a `lineage.md` file in `/docs`

---

## Agent Architecture

### Agent 1 — The Doctor (RAG Agent)
- **Purpose:** Answers natural language queries about London's health using historical Gold-layer data
- **Framework:** LangChain + LangGraph
- **Memory:** ChromaDB vector store (semantic retrieval over embedded health score descriptions)
- **Tools registered:**
  - `get_borough_health(borough_name, time_range)` — queries DuckDB Gold layer
  - `get_london_score(timestamp)` — returns overall city score
  - `get_trend(borough_name, metric, days)` — returns trend direction over N days
  - `compare_boroughs(metric, top_n)` — ranks boroughs by a given signal
- **Input:** Natural language question from frontend or API
- **Output:** Natural language response with cited Guardian headline links and data points

### Agent 2 — The Bulletin Agent
- **Purpose:** Generates a structured weekly city health digest
- **Framework:** LangChain prompt chaining
- **Trigger:** Scheduled (daily via APScheduler) AND on-demand via frontend button
- **Chain:**
  1. Retrieve current Gold-layer scores for all boroughs
  2. Query Doctor agent for top 3 notable trends this week
  3. Fetch latest Guardian headlines for context (headline + URL only)
  4. Synthesise into structured bulletin: overall score, borough highlights, trend narrative, cited sources
- **Output:** Markdown bulletin stored in `/data/bulletins/` and served via API

### LLM
- **Model:** `claude-haiku-4-5` via Anthropic API
- **Used for:** Doctor agent reasoning, Bulletin synthesis
- **Not used for:** Sentiment scoring (handled locally)
- **Privacy justification:** Only Gold-layer aggregated public data reaches the external model — no PII, no raw post content

---

## API Design (FastAPI)

Base URL: `http://localhost:8000`

### Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Service health check |
| `GET` | `/london/score` | Current overall London health score |
| `GET` | `/boroughs` | List all boroughs with current scores |
| `GET` | `/borough/{name}` | Full health breakdown for a borough |
| `GET` | `/borough/{name}/trend` | 7-day trend for a borough |
| `POST` | `/agent/query` | Natural language query to Doctor agent |
| `GET` | `/bulletin/latest` | Latest generated bulletin |
| `POST` | `/bulletin/generate` | Trigger on-demand bulletin generation |

### Response format
All endpoints return JSON. Health scores are always in the range 0–100.

### MCP-style tool definitions
FastAPI routes are decorated with machine-readable descriptions to expose CityScan as a tool-invocable service, consistent with MCP patterns described in the assignment brief.

---

## Frontend (Next.js)

### Pages

**`/` — Dashboard**
- London map with borough-level colour coding (green → red based on composite score)
- Overall London health score with organ breakdown panel
- Last updated timestamp

**`/borough/[name]` — Borough Detail**
- Per-organ score breakdown with sparkline trends
- Recent Guardian headlines cited as sources (headline + link only)

**`/ask` — Ask The Doctor**
- Natural language input → streams Doctor agent response
- Shows cited data sources inline

**`/bulletin` — Weekly Bulletin**
- Latest bulletin rendered as formatted report
- "Generate new bulletin" button (triggers `POST /bulletin/generate`)

### Design principles
- Borough health score displayed as a body organ diagram (SVG) alongside the map
- Colour scale: 80–100 = green, 50–79 = amber, 0–49 = red
- Mobile responsive

---

## Infrastructure

### Docker Compose services
| Service | Description |
|---|---|
| `ingestion` | APScheduler process running all data source collectors |
| `pipeline` | Bronze → Silver → Gold transformation runner |
| `api` | FastAPI backend |
| `frontend` | Next.js app |
| `chromadb` | ChromaDB vector store server |

Single command to run everything: `docker compose up`

### Environment variables (`.env`, never committed)
```
ANTHROPIC_API_KEY=
OPENAQ_API_KEY=
GUARDIAN_API_KEY=
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USER_AGENT=
TFL_APP_KEY=
```

### Git
- `.env` and `/data/` in `.gitignore`
- `.env.example` committed with placeholder values
- Commits follow conventional commits format: `feat:`, `fix:`, `data:`, `agent:`, `docs:`
- Multiple commits demonstrating evolution of the system (required by brief)

---

## Out of Scope (for this submission)

- Predictive / forecasting layer (architecture leaves room for it)
- User authentication
- Database beyond DuckDB (no Postgres, no cloud DB)
- Cloud deployment (runs locally via Docker)
- Real-time websocket streaming (polling is fine)

---

## File Structure

```
city-scan-london/
├── CLAUDE.md
├── PRD.md
├── README.md
├── docker-compose.yml
├── .env.example
├── .gitignore
├── docs/
│   └── lineage.md
├── ingestion/
│   ├── scheduler.py
│   └── sources/
│       ├── openaq.py
│       ├── tfl.py
│       ├── met_police.py
│       ├── reddit.py
│       └── guardian.py
├── pipeline/
│   ├── bronze.py
│   ├── silver.py
│   ├── gold.py
│   └── schemas.py
├── sentiment/
│   └── scorer.py
├── agents/
│   ├── doctor.py
│   ├── bulletin.py
│   └── tools/
│       ├── health_score.py
│       ├── borough_query.py
│       └── trend_analysis.py
├── api/
│   ├── main.py
│   └── routers/
│       ├── health.py
│       ├── boroughs.py
│       └── agent.py
├── frontend/
│   └── (Next.js app — next.js init here)
├── data/
│   ├── bronze/
│   ├── silver/
│   ├── gold/
│   └── bulletins/
├── embeddings/
│   └── (ChromaDB persistence)
└── docker/
    ├── Dockerfile.api
    ├── Dockerfile.ingestion
    └── Dockerfile.frontend
```
