# CityScan London — Product Requirements Document

## Overview

CityScan is a live urban health monitoring platform that models London as a human body. Each data source maps to a biological system — air quality to lungs, transport to arteries, public sentiment to the brain, crime to the immune system, green space coverage to the skin. The system produces a health score per London borough (updated hourly; some sources carry institutional lag — see Data Lag note below) and an overall city health score, queryable via a natural language agent interface and summarised in a daily LLM-generated bulletin.

**Tagline:** *A CT scan for the city.*

**Target users:** Urban planners, public health researchers, city councils, emergency services, civic data analysts.

**GitHub repo:** `city-scan-london` (public)

---

## The Biological Metaphor


| Organ             | Data Source                                     | Signal                                      | Update Cadence | Data Lag                          |
| ----------------- | ----------------------------------------------- | ------------------------------------------- | -------------- | --------------------------------- |
| 🫁 Lungs          | OpenAQ API                                      | PM2.5, NO2 per borough                       | Hourly         | ~1 hour                           |
| 🩸 Arteries       | TfL Unified API                                 | Tube line status & severity scores          | Hourly         | Real-time                         |
| 🧠 Brain          | Guardian API + BBC News RSS                     | NLP sentiment score from headlines           | Hourly         | ~1 hour                           |
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
- Green space data is static (GLA Green Cover 2024) and stored in `/data/static/green_space.json` rather than bronze (no raw API response to capture)
- Nothing is transformed at this stage
- Ingestion runs on a schedule via APScheduler inside the `ingestion` service

**Silver layer** — cleaned & normalised

- All sources normalised to a common schema in DuckDB:
`(borough_code, borough_name, timestamp, metric_name, raw_value, normalised_score, source, ingested_at, pipeline_stage)`
- Borough codes follow ONS Greater London Authority boundary codes (static lookup file)
- Guardian and BBC text is processed locally by a sentiment model before entering Silver — raw content never leaves the machine. Reddit ingestion code exists but is currently inactive (Reddit blocks public JSON API access with 403 since April 2026)
- Sentiment model: `cardiffnlp/twitter-roberta-base-sentiment` (runs on CPU)

**Silver Detail layer** — contextual per-item data

- Two tables (`silver_detail` + `silver_headlines`) storing per-item data for agent breakdown queries
- `silver_detail`: crime categories per borough, tube line statuses, AQ station readings, NHS trust performance, ward-level green space coverage
- `silver_headlines`: individual news headlines with per-title sentiment scores
- These do **not** feed into gold scores — purely additive context for the Doctor Agent
- Retention: 90 days (same cleanup job as silver_metrics)

**Gold layer** — aggregated health scores

- One row per borough per ingestion cycle:
`(borough_code, borough_name, timestamp, air_score, transit_score, sentiment_score, immune_score, green_space_score, composite_score, ingested_at, pipeline_stage)`
- Stored in DuckDB (structured) and embedded into ChromaDB (vector, for RAG)
- Composite score = weighted average: air (20%), transit (20%), sentiment (20%), immune (20%), green space (20%)
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
- **Tools registered (hybrid architecture — 5 curated + 1 flexible + 1 RAG + 1 deprivation):**
  - `get_borough_health(borough)` — full score breakdown for a single borough (curated)
  - `get_london_score()` — overall city score averaged across all boroughs (curated)
  - `get_trend(borough, metric, days)` — trend direction + delta over N days (curated)
  - `compare_boroughs(metric, top_n, ascending)` — ranks boroughs by a given signal (curated)
  - `get_deprivation(borough)` — IMD 2025 deprivation rank + 7 domain sub-scores (income, employment, education, health, crime, barriers, living) from static JSON
  - `run_sql(query)` — read-only SQL against `gold_scores` / `silver_metrics` / `silver_detail` / `silver_headlines` for analytical questions the curated tools can't answer (flexible, guarded)
  - `search_scores(query, n_results, borough_code)` — semantic similarity search over ChromaDB gold_scores embeddings for RAG context retrieval
- **Evidence synthesis:** The Doctor synthesises cross-domain data with policy-grounded context. System prompt loads verified London policy references from `data/static/policy_context.md` for hallucination prevention and contextual grounding. Adapts response depth based on question framing (policy/public) or explicit role field.
- **Role-aware queries:** API accepts optional `role` field (`policy|public`). Auto-detected from question when not specified.
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
- **Tools exposed:** `get_borough_health`, `get_london_score`, `get_trend`, `compare_boroughs`, `run_sql`, `search_scores` (6 of 7 Doctor tools — `get_deprivation` not yet exposed via MCP)
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
| `GET`  | `/boroughs/deprivation` | IMD 2025 deprivation data for all boroughs              |
| `POST` | `/internal/reset-db`    | Release DuckDB read connection (internal)               |


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
- Floating action buttons: "Analytics" and "Ask the Doctor"
- Panels slide in from the right when activated:
  - **Analytics panel** — scrollable analytics suite with five views: (1) Health vs Deprivation scatter plot with labelled outliers and trend line, (2) cross-domain correlation insight (Pearson r, auto-computed on page load), (3) borough radar comparison (two boroughs, five axes), (4) organ history time series (per-borough, 7/14/30d window), (5) critical organs triage table (sortable, filterable by organ)
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
SCORE_WEIGHTS=0.20,0.20,0.20,0.20,0.20
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
- **Prescriptive policy engine** — CityScan surfaces evidence and patterns, not policy directives. Policy context is for grounding, not prescription.

---

## Scaling & Production Readiness

The current architecture is a working prototype deployed on a single VPS. To scale to production serving multiple councils and public users:

- **Database:** DuckDB → PostgreSQL with connection pooling (pgBouncer). DuckDB is single-writer and not thread-safe for concurrent access. PostgreSQL handles hundreds of concurrent reads/writes. The pipeline's standard SQL makes migration straightforward.
- **Caching:** Add Redis between the API and database. Borough scores change hourly — cache them for 60 minutes. Eliminates 99% of database reads on the serving path.
- **Reverse proxy:** Caddy or nginx in front of API + frontend. HTTPS termination via Let's Encrypt, proper `X-Forwarded-For` handling, rate limiting at the proxy layer.
- **LLM cost:** Fine-tune an open-source model (Llama/Mistral 7B-13B) on accumulated agent_logs interaction data. The logging infrastructure already captures training data (queries, tool outputs, final responses). Eliminates per-query API cost and reduces latency to sub-second.
- **Deployment model:** On-premise for councils — each borough runs their own CityScan instance with custom policy context documents. DuckDB's zero-dependency embedded model is an advantage here (no database server to install).
- **CI/CD:** GitHub Actions workflow: push to main → run tests → build Docker images → deploy to VPS automatically.
- **Monitoring:** Prometheus + Grafana for container health, API latency, pipeline success rates, LLM token usage.

---

## Future Enhancements

Ideas validated during development but deferred to keep scope manageable:

### Data & Analytics

- **Predictive layer** — time-series forecasting (Prophet/ARIMA) on gold_scores once 3-6 months of data accumulates. The pipeline already produces hourly time-series data across 5 dimensions for 33 boroughs — the input layer for predictive models is built.
- **Anomaly detection** — flag borough scores deviating >2 standard deviations from their rolling mean. Surface as visual indicators on the map and in the bulletin.
- **Ambient population for crime** — replace residential per-capita with workday/daytime population (Census 2021 or TfL tap-in/tap-out data) for fairer crime normalisation in commuter boroughs.
- **PTAL integration** — TfL Public Transport Accessibility Levels for real SDG 11.2 coverage (who can ACCESS transport, not just service status).
- **Housing data** — Land Registry prices or GLA housing stats as a 6th organ ("Skeleton"), aligned with SDG 11.1 (affordable housing).
- **Noise pollution** — DEFRA noise maps as an additional environmental signal for the Lungs organ.
- **Multi-modal transit scoring** — TfL's status API supports bus, Overground, Elizabeth line, and DLR in the same endpoint. Adding these modes gives transit scores to the 7 boroughs currently missing tube coverage.
- **Borough-level sentiment via NER** — Named Entity Recognition to extract borough names from headlines and assign per-borough sentiment scores instead of city-wide.
- **Correlation engine** — algorithmically discover which IMD domains correlate most strongly with which organ scores across all 33 boroughs.
- **Trend minimum data guard** — suppress trend arrows and bulletin trend narratives when `data_points < 24` (less than 1 day of hourly data). With few data points, score changes reflect input volatility (tube disruptions clearing, different headlines), not real urban health trends. Mark as `"insufficient"` instead of `"improving"/"declining"`.
- **TfL reason text for RAG** — surface the TfL `reason` field (e.g. "points failure at Queen's Park") to explain why a line is disrupted.

### Frontend & UX

- **IMD overlay on map** — toggle deprivation as border thickness on borough paths.
- **Time slider** — drag to see how the thermal map changed over days/weeks using accumulated gold_scores history.
- **Notification/alerting** — subscribe to a borough, get email when any organ drops below a threshold.
- **Embed mode** — `<iframe>` embed code for council websites to display their borough health card.
- **Mobile-responsive redesign** — proper layout for 5-metric header on narrow screens.

### Agent & NLP

- **Fine-tuned local model** — train an open-source model (Llama/Mistral) on accumulated agent_logs interaction data. Zero API cost, sub-second local inference. The logging infrastructure already captures training data (queries, tool outputs, final responses).
- **Sonnet/Opus as default** — compatibility fixes in place (timeout, recursion limit, max_tokens). Blocked by API cost ($0.15-0.25/query vs $0.03 for Haiku). Viable when query volume justifies the quality improvement.
- **Conversation memory** — Doctor remembers prior questions within a session for multi-turn context.
- **Voice input/output** — Web Speech API for spoken queries and diagnosis narration.
- **Structured report format** — dedicated output: Summary → Organ Breakdown → Trends → Key Findings.
- **Citation links** — recommendations link to relevant policy documents.
- **Confidence scores** — Doctor indicates "high confidence" on fresh data, "lower confidence" on stale readings.

### Infrastructure & Deployment

- **PostgreSQL migration** — replace DuckDB for concurrent multi-user support with connection pooling.
- **Redis caching** — cache borough scores (change hourly), eliminate 99% of database reads on the serving path.
- **On-premise deployment** — councils run their own CityScan instance with custom policy context documents. DuckDB's zero-dependency embedded model is an advantage here.
- **Multi-city framework** — parameterise borough codes, data sources, and SVG paths for any UK city. IMD data already covers all 296 English local authorities. OpenAQ, Police API, and NHS data are national.
- **User accounts** — save favourite boroughs, track notification preferences.
- **API keys for external consumers** — other tools query CityScan's scored data.
- **Automated data quality checks** — flag when a source returns suspiciously few rows or scores shift >20 points in one cycle.
- **Real-time WebSocket** — push score updates to frontend as the pipeline runs.

### Vision

Designed for London, architected for any city where open data exists. The pipeline is source-agnostic — swap source modules for local equivalents (OpenAQ is global, police/health APIs exist per country, GTFS is a transit standard). Policy context is a pluggable document, community-maintainable. IMD data covers all 296 English local authorities. Multi-city deployment requires only new geo mappings and source adapters.

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
│   ├── generate_geo_mappings.py ← Fetches borough/TfL/NHS geo data from public APIs
│   ├── fetch_population.py      ← Downloads ONS population data for per-capita normalisation
│   ├── fetch_green_space.py     ← Downloads GLA Green Cover 2024 XLSX → data/static/green_space.json
│   └── fetch_imd.py             ← Downloads IMD 2025 deprivation data → data/static/imd_borough.json
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
│       ├── nhs_ae.py
│       └── green_space.py
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
│       ├── deprivation.py          ← IMD 2025 deprivation lookup (static JSON, no DuckDB)
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
│   └── (Next.js app — see docs/frontend-spec.md)
│       ├── components/panels/AnalyticsPanel.tsx   ← Health vs Deprivation scatter panel
│       ├── components/charts/DeprivationScatter.tsx ← Recharts scatter: IMD rank vs health score
│       ├── components/charts/BoroughRadar.tsx ← Recharts radar: 2-borough comparison across 5 organs
│       ├── components/charts/BoroughTimeSeries.tsx ← Recharts line: organ score history over time
│       ├── components/charts/WorstOrganTable.tsx ← Sortable triage table: worst organ per borough
│       └── ...
├── data/
│   ├── bronze/
│   ├── silver/
│   ├── gold/
│   ├── static/                  ← pre-processed reference data (green_space.json, population)
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

