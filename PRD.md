# CityScan London — Product Requirements Document

## Overview

CityScan is a live urban health diagnostic platform that models London as a human body. Each data source maps to a biological system — air quality to lungs, transport to arteries, public sentiment to the brain, crime to the immune system. The system produces a real-time health score per London borough and an overall city health score, queryable via a natural language agent interface and summarised in a daily LLM-generated bulletin.

**Tagline:** *A CT scan for the city.*

**Target users (enterprise framing):** Urban planners, city councils, emergency services, property analysts, public health researchers.

**GitHub repo:** `city-scan-london` (public)

---

## The Biological Metaphor


| Organ             | Data Source                                     | Signal                                      | Update Cadence | Data Lag                          |
| ----------------- | ----------------------------------------------- | ------------------------------------------- | -------------- | --------------------------------- |
| 🫁 Lungs          | OpenAQ API                                      | PM2.5, NO2 per borough                       | Hourly         | ~1 hour                           |
| 🩸 Arteries       | TfL Unified API                                 | Tube line status & severity scores          | Hourly         | Real-time                         |
| 🧠 Brain          | Reddit (r/london) + Guardian API + BBC News RSS | NLP sentiment score from posts & headlines  | Hourly         | ~1 hour                           |
| 🛡️ Immune System | Met Police API + NHS England A&E stats          | Per-capita crime (winsorised) + A&E pressure index | Monthly        | Crime: ~2 months · A&E: ~2 months |
| 🌿 Skin           | GLA Green Cover 2024                            | Green space coverage per borough (satellite NDVI)  | Yearly         | Static (2024 snapshot)            |


Each signal is normalised to a 0–100 score (100 = healthy). The composite borough health score is a weighted average of all five signals (default 0.20 each, configurable via `SCORE_WEIGHTS`). The overall London score aggregates all boroughs.

> **Note on immune system data lag:** Unlike lungs and arteries which reflect near-real-time conditions, the immune system score carries inherent institutional lag. Crime statistics are published ~2 months after the reference period; NHS A&E figures are published monthly, also with a ~2 month lag. This mirrors the biological reality — immune responses are slower to manifest and measure than vital signs. The frontend surfaces the `as_of_date` for immune scores so users are never misled about freshness.

---

## System Architecture

### Data Tier — Bronze / Silver / Gold

**Bronze layer** — raw ingestion

- Raw API responses stored as timestamped JSON files
- One directory per source: `/data/bronze/openaq/`, `/data/bronze/tfl/`, `/data/bronze/reddit/`, `/data/bronze/guardian/`, `/data/bronze/bbc/`, `/data/bronze/met_police/`
- Nothing is transformed at this stage
- Ingestion runs on a schedule via APScheduler inside the `ingestion` service

**Silver layer** — cleaned & normalised

- All sources normalised to a common schema in DuckDB:
`(borough_code, borough_name, timestamp, metric_name, raw_value, normalised_score, source, ingested_at, pipeline_stage)`
- Borough codes follow ONS Greater London Authority boundary codes (static lookup file)
- Reddit, Guardian, and BBC text is processed locally by a sentiment model before entering Silver — raw post content never leaves the machine
- Sentiment model: `cardiffnlp/twitter-roberta-base-sentiment` (runs on CPU)

**Silver Detail layer** — contextual per-item data

- Two tables (`silver_detail` + `silver_headlines`) storing per-item data for agent breakdown queries
- `silver_detail`: crime categories per borough, tube line statuses, AQ station readings, NHS trust performance, ward-level green space coverage
- `silver_headlines`: individual news/Reddit headlines with per-title sentiment scores
- These do **not** feed into gold scores — purely additive context for the Doctor Agent
- Retention: 90 days (same cleanup job as silver_metrics)

**Gold layer** — aggregated health scores

- One row per borough per ingestion cycle:
`(borough_code, borough_name, timestamp, air_score, transit_score, sentiment_score, immune_score, composite_score, ingested_at, pipeline_stage)`
- Stored in DuckDB (structured) and embedded into ChromaDB (vector, for RAG)
- Composite score = weighted average: air (25%), transit (25%), sentiment (25%), immune (25%)
- Weights are configurable via environment variable `SCORE_WEIGHTS`

### Pipeline execution model

The `ingestion` service owns the full pipeline. APScheduler runs the complete chain on each tick:

```
fetch() → bronze.save() → silver.transform() → silver.detail() → gold.aggregate() → embed.embed_gold_scores()
```

There is no separate pipeline container. The `pipeline/` directory contains transformation logic as importable functions called by the scheduler. A manual one-shot trigger is available for development:

```bash
python ingestion/run_pipeline.py   # runs full chain once and exits
```

### Storage

- **DuckDB** — primary structured store for Silver and Gold layers (`data/cityscan.duckdb`); agent logs stored in separate file (`data/agent_logs.duckdb`) to avoid connection conflicts
- **ChromaDB** — vector store for Gold-layer embeddings, enabling semantic RAG queries
- **Local filesystem** — Bronze JSON files, organised by source and date

### Data Lineage

- Each record carries `source`, `ingested_at`, and `pipeline_stage` fields through all three layers
- `docs/lineage.md` contains a Mermaid diagram showing the full data flow from source → Bronze → Silver → Gold → Agent
- Transformations documented in code comments alongside the diagram

---

## Agent Architecture

### Agent 1 — The Doctor (RAG Agent) — IMPLEMENTED

- **Purpose:** Answers natural language queries about London's health using historical Gold-layer data
- **Framework:** LangGraph `create_react_agent` + LangChain tools
- **LLM:** `claude-haiku-4-5` via `langchain-anthropic`
- **Memory:** ChromaDB vector store (semantic retrieval over embedded health score descriptions)
- **Tools registered (hybrid architecture — 4 curated + 1 flexible + 1 RAG):**
  - `get_borough_health(borough)` — full score breakdown for a single borough (curated)
  - `get_london_score()` — overall city score averaged across all boroughs (curated)
  - `get_trend(borough, metric, days)` — trend direction + delta over N days (curated)
  - `compare_boroughs(metric, top_n, ascending)` — ranks boroughs by a given signal (curated)
  - `run_sql(query)` — read-only SQL against `gold_scores` / `silver_metrics` / `silver_detail` / `silver_headlines` for analytical questions the curated tools can't answer (flexible, guarded)
  - `search_scores(query, n_results, borough_code)` — semantic similarity search over ChromaDB gold_scores embeddings for RAG context retrieval
- **Input:** Natural language question from frontend or API
- **Output:** Structured JSON with two fields:
  - `answer` — natural language response (streamed via SSE)
  - `sources` — list of grounded data points used to generate the answer, each with `type`, `data`, and optionally `url` (for Guardian headlines). Enables the user to verify any claim against its source.
- **Streaming:** `POST /agent/query` returns a Server-Sent Events stream. Events: `data: {"type": "token", "content": "..."}` for tokens, `data: {"type": "sources", "sources": [...]}` for sources, `data: [DONE]` as sentinel.
- **Hallucination mitigation:** Every factual claim in the answer is grounded in a retrieved tool output. The `sources` field makes this verifiable. Tool outputs are stored in `agent_logs` for audit.
- **`run_sql` guardrails (13-layer security model):**
  1. Read-only DuckDB connection — engine-enforced, all write/DDL operations blocked
  2. Query length limit — rejects queries longer than 10,000 characters
  3. SQL comments stripped before validation (prevents hiding keywords in `--` or `/* */` comments)
  4. Semicolon rejection — blocks multi-statement payloads
  5. SELECT-only enforcement — query must start with SELECT
  6. Keyword blocklist — rejects write/DDL keywords as defence in depth
  7. Metadata function blocklist — blocks all `duckdb_*()` introspection functions
  8. File-read function blocklist — blocks `read_csv_auto`, `read_parquet`, `read_json_auto`, `glob`, etc.
  9. File path table reference blocklist — blocks `FROM '/path/...'` patterns
  10. Table blocklist + allowlist — only `gold_scores`, `silver_metrics`, `silver_detail`, `silver_headlines` queryable
  11. WHERE clause enforcement — detail tables require a WHERE clause
  12. Row limit — outer LIMIT 100 (50 for detail tables)
  13. Text field truncation — `detail_text`, `label`, `title` capped at 200 chars in output
  - Plus: input sanitisation on detail writes, sanitised error messages

### Agent 2 — The Bulletin Agent

- **Purpose:** Generates a structured daily city health digest
- **Framework:** LangChain prompt chaining
- **Trigger:** Scheduled (daily via APScheduler) AND on-demand via `POST /bulletin/generate`
- **Chain:**
  1. Fetch current Gold-layer scores for all boroughs directly from DuckDB
  2. Query DuckDB for top 3 notable trends this week (direct query, not via Doctor agent)
  3. Fetch latest Guardian headlines for context (headline + URL only)
  4. Synthesise into structured bulletin: overall score, borough highlights, trend narrative, cited sources
- **Output:** Markdown bulletin stored in `/data/bulletins/YYYY-MM-DD.md` and served via API

### LLM

- **Model:** `claude-haiku-4-5` via Anthropic API
- **Used for:** Doctor agent reasoning, Bulletin synthesis
- **Not used for:** Sentiment scoring (handled locally)
- **Privacy justification:** Gold-layer scores and silver-layer contextual detail (crime categories, tube line statuses, station readings, headline titles) reach the external model — no PII, no raw post body content

---

## Agent Evaluation & Observability

### agent_logs table (DuckDB)

Every Doctor agent interaction is recorded:

```sql
CREATE TABLE agent_logs (
    id             VARCHAR NOT NULL,   -- UUID
    timestamp      VARCHAR NOT NULL,   -- ISO 8601 UTC
    query          VARCHAR,            -- user's question
    tools_called   VARCHAR,            -- JSON array: ["get_borough_health", "get_trend"]
    tool_inputs    VARCHAR,            -- JSON: parameters passed to each tool
    tool_outputs   VARCHAR,            -- JSON: raw data returned by each tool
    sources_cited  VARCHAR,            -- JSON: sources included in the response
    final_response VARCHAR,            -- full LLM answer
    latency_ms     INTEGER,            -- total wall time
    model_used     VARCHAR             -- e.g. "claude-haiku-4-5"
);
```

### bulletin_logs table (DuckDB)

```sql
CREATE TABLE bulletin_logs (
    id             VARCHAR NOT NULL,
    timestamp      VARCHAR NOT NULL,
    trigger        VARCHAR,            -- "scheduled" or "manual"
    scores_used    VARCHAR,            -- JSON snapshot of Gold scores at generation time
    headlines_used VARCHAR,            -- JSON array of Guardian headlines used
    output_path    VARCHAR,            -- path to the saved .md file
    latency_ms     INTEGER
);
```

---

## MCP Server

The Doctor agent tools are also exposed as a Model Context Protocol (MCP) server, making CityScan queryable by any MCP-compatible client (Claude Desktop, other agents).

- **Location:** `mcp_server/server.py`
- **SDK:** `mcp` Python package
- **Port:** 8002
- **Tools exposed:** `get_borough_health`, `get_london_score`, `get_trend`, `compare_boroughs`, `run_sql`, `search_scores`
- **Transport:** Streamable HTTP transport on port 8002 (path: `/mcp`)

This means any external agent can discover and invoke CityScan's data tools without going through the FastAPI REST layer.

---

## API Design (FastAPI)

Base URL: `http://localhost:8000`

### Endpoints


| Method | Path                    | Description                                             |
| ------ | ----------------------- | ------------------------------------------------------- |
| `GET`  | `/health`               | Service health check                                    |
| `GET`  | `/london/score`         | Current overall London health score                     |
| `GET`  | `/boroughs`             | List all boroughs with current scores                   |
| `GET`  | `/borough/{name}`       | Full health breakdown for a borough                     |
| `GET`  | `/borough/{name}/trend` | 7-day trend for a borough                               |
| `POST` | `/agent/query`          | Doctor agent — returns SSE stream (`text/event-stream`) |
| `GET`  | `/bulletin/latest`      | Latest generated bulletin                               |
| `POST` | `/bulletin/generate`    | Trigger on-demand bulletin generation                   |


### Response format

All non-streaming endpoints return JSON. Health scores are always 0–100.

`POST /agent/query` returns `Content-Type: text/event-stream`. Events:

- `data: {"type": "token", "content": "..."}` — streamed answer tokens
- `data: {"type": "sources", "sources": [...]}` — final event with grounded sources list
- `data: [DONE]` — stream sentinel

### MCP-style tool definitions

FastAPI routes are decorated with machine-readable descriptions consistent with MCP patterns.

---

## Frontend (Next.js)

### Architecture

Single-page application with panel-based navigation. All interactions happen on the root page (`/`) using sliding panels instead of separate routes.

**Landing state:** Bulletin rendered as a scan report with X-ray blue London map. Click "Enter Live Map" to transition.

**Live map state:** Interactive thermal map with boroughs coloured by health score. UI elements:
- Header: vital signs with EKG lines, metric filter buttons
- Floating action buttons: "Daily Bulletin" and "Ask the Doctor"
- Panels slide in from the right when activated:
  - **Bulletin panel** — latest bulletin markdown rendered as formatted report
  - **Doctor chat panel** — natural language input with SSE streaming response

### Design principles

- Borough health score displayed as a body organ diagram (SVG) alongside the map
- Colour scale: 6-stop thermal gradient (deep blue = healthy → red = critical)
- Mobile responsive

---

## Infrastructure

### Docker Compose services


| Service      | Description                                                                    | Port |
| ------------ | ------------------------------------------------------------------------------ | ---- |
| `ingestion`  | APScheduler process — fetches all sources AND runs Bronze→Silver→Gold pipeline | —    |
| `api`        | FastAPI backend                                                                | 8000 |
| `mcp_server` | MCP server exposing Doctor agent tools                                         | 8002 |
| `frontend`   | Next.js app                                                                    | 3000 |
| `chromadb`   | ChromaDB vector store server                                                   | 8000 (internal) |


Single command to run everything: `docker compose up`

### Environment variables (`.env`, never committed)

```
ANTHROPIC_API_KEY=
OPENAQ_API_KEY=
GUARDIAN_API_KEY=
REDDIT_USER_AGENT=cityscan/1.0
TFL_APP_KEY=
SCORE_WEIGHTS=0.25,0.25,0.25,0.25
CHROMADB_HOST=localhost
CHROMADB_PORT=8001                        # local dev default; Docker overrides to 8000
MCP_PORT=8002
MCP_HOST=127.0.0.1
AGENT_RATE_LIMIT_PER_IP_HOUR=15
AGENT_RATE_LIMIT_PER_IP_DAY=40
AGENT_RATE_LIMIT_GLOBAL_DAY=150
```

### Git

- `.env` and `/data/` in `.gitignore`
- `.env.example` committed with placeholder values
- Commits follow conventional commits format: `feat:`, `fix:`, `data:`, `agent:`, `docs:`
- Multiple commits demonstrating evolution of the system

---

## Out of Scope (for this submission)

- Predictive / forecasting layer (architecture leaves room for it)
- User authentication
- Database beyond DuckDB (no Postgres, no cloud DB)
- Cloud deployment (runs locally via Docker)
- Real-time WebSocket bidirectional streaming (SSE one-way streaming is in scope)
- GraphRAG (borough graph relationships — noted as future enhancement)

---

## Future Enhancements (post-submission)

Ideas validated during development but deferred to keep scope manageable:

- **TfL reason text for RAG** — the TfL API returns a `reason` field (e.g. "points failure at Queen's Park") alongside severity. Currently unused for scoring (severity integer is sufficient), but the Doctor Agent could retrieve it to explain *why* a line is disrupted when answering queries. Store in bronze, surface via agent tool.
- **Per-capita crime normalisation** — current crime scoring uses min-max (relative ranking across boroughs). Adding ONS population data would enable per-capita normalisation, making scores fairer for high-population boroughs. Population data is available from the same ONS API used for borough centroids.
- **Multi-modal transit scoring** — current transit data covers only tube. TfL's status API supports bus, Overground, Elizabeth line, and DLR in the same endpoint (`GET /line/mode/tube,overground,elizabeth-line,dlr/status`). Adding these modes would: (a) give transit scores to the 7 boroughs currently missing tube coverage, (b) let boroughs with alternatives (e.g. DLR + Jubilee in Greenwich) score based on their best available mode rather than worst tube line. This is a bronze-level fetch change — same API, wider mode filter.
- **Borough-level sentiment via NER** — current sentiment is city-wide (all 33 boroughs get the same score). Named Entity Recognition could extract borough names from Reddit/BBC/Guardian text and assign sentiment at borough level. Out of scope due to NER complexity and sparse borough mentions in most articles.

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
│   ├── lineage.md               ← Mermaid diagram + transformation notes
│   └── schema.dbml              ← DuckDB schema for dbdiagram.io
├── scripts/
│   └── generate_geo_mappings.py ← Fetches borough/TfL/NHS geo data from public APIs
├── ingestion/
│   ├── scheduler.py             ← APScheduler: fetch + full pipeline chain
│   ├── run_pipeline.py          ← one-shot manual trigger (dev only)
│   └── sources/
│       ├── openaq.py
│       ├── tfl.py
│       ├── met_police.py
│       ├── reddit.py
│       ├── guardian.py
│       ├── bbc.py
│       └── nhs_ae.py
├── pipeline/
│   ├── bronze.py                ← save raw JSON to /data/bronze/
│   ├── silver.py                ← normalise to DuckDB silver schema
│   ├── gold.py                  ← aggregate scores to DuckDB gold schema
│   ├── embed.py                 ← embed gold scores into ChromaDB
│   ├── chroma_client.py         ← lazy ChromaDB write-side singleton
│   ├── schemas.py               ← loads lookups.json + DuckDB DDL
│   └── lookups.json             ← auto-generated geo mappings (committed)
├── sentiment/
│   └── scorer.py
├── agents/
│   ├── doctor.py                ← LangGraph ReAct agent + SSE streaming
│   ├── bulletin.py              ← LangChain prompt chain
│   ├── logging_db.py            ← manages agent_logs.duckdb (agent_logs + bulletin_logs)
│   └── tools/
│       ├── __init__.py
│       ├── db.py
│       ├── health_score.py
│       ├── borough_query.py
│       ├── trend_analysis.py
│       ├── sql_query.py
│       ├── rag_query.py
│       ├── chroma_client.py
│       └── langchain_tools.py
├── mcp_server/
│   └── server.py                ← MCP server wrapping Doctor agent tools
├── api/
│   ├── main.py
│   ├── db.py                    ← lazy read-only DuckDB connection + reset for ingestion
│   ├── rate_limit.py            ← per-IP + global rate limiting for Doctor Agent
│   └── routers/
│       ├── health.py
│       ├── boroughs.py
│       └── agent.py             ← SSE streaming endpoint
├── frontend/
│   └── (Next.js app)
├── data/
│   ├── bronze/
│   ├── silver/
│   ├── gold/
│   └── bulletins/
├── embeddings/
│   └── (ChromaDB persistence)
└── docker/
    ├── Dockerfile.api
    ├── Dockerfile.chromadb
    ├── Dockerfile.frontend
    ├── Dockerfile.ingestion
    └── Dockerfile.mcp
```

