# CityScan London

> Placed 2nd at the Analytics for Society Awards 2026 — UCL School of Management × Imperial Gandhi Centre × Institute of Analytics.

A live urban health monitoring platform that models London as a human body.

Multiple public data sources map to five biological systems, producing a health score per London borough (updated hourly for the live signals; some sources carry institutional lag) — queryable via a natural language agent for cross-domain data integration, and summarised in a daily LLM-generated bulletin. External-context layers (IMD 2025, ONS Housing Affordability 2025, ONS Health Index 2021, TfL PTAL 2015) sit alongside the live pipeline for equity, validation, and access analysis.

| System | Data Source | Signal |
|---|---|---|
| 🫁 Lungs | OpenAQ (live) + GLA LAEI 2022 (modelled) | Air quality (PM2.5, NO2) — live sensor readings **plus** modelled population-weighted annual mean for full 33/33 borough coverage |
| 🩸 Arteries | TfL API | Tube line status & severity scores |
| 🧠 Brain | Guardian + BBC News | Public sentiment (NLP) |
| 🛡️ Immune system | Met Police API + NHS England A&E | Per-capita crime (log-transformed) + A&E pressure |
| 🌿 Skin | GLA Green Cover 2024 + ONS ward populations | Green space **coverage** and **ward-population-weighted access** per borough |

## Stack

Python 3.11 · DuckDB · ChromaDB · LangChain + LangGraph · Claude Haiku · FastAPI · Next.js · Docker

## Setup

```bash
cp .env.example .env   # add your API keys
python scripts/generate_geo_mappings.py             # fetch borough/TfL/NHS geographic data
python scripts/fetch_population.py                  # fetch ONS borough populations (per-capita crime)
python scripts/fetch_population.py --wards          # fetch ONS ward populations (access-weighted green)
python scripts/fetch_green_space.py                 # fetch GLA green cover data
python scripts/fetch_laei.py                        # fetch GLA LAEI 2022 modelled air quality
python scripts/fetch_imd.py                         # fetch IMD 2025 deprivation data
python scripts/refresh_housing_affordability.py     # fetch ONS Housing Affordability Ratio (Table 5c, annual)
python scripts/refresh_ons_health_index.py          # fetch ONS Health Index for England (used as external validation)
python scripts/fetch_ptal.py                        # fetch TfL PTAL 2015 borough averages (SDG 11.2 access measure)
python -m scripts.compute_score_quality             # bootstrap CIs + per-organ score-quality flags from gold time-series
```

All `fetch_*` and `refresh_*` scripts above are one-shot — re-run when the upstream source publishes a new vintage. Green cover, IMD, housing affordability, and the Health Index are all yearly refreshes. PTAL is updated only on major TfL network changes (current edition: 2015). `compute_score_quality.py` is a periodic job (run after the gold layer is repopulated).

## Run

```bash
# Run the data pipeline (fetches live data → scores all 33 boroughs)
python ingestion/run_pipeline.py

# Start the API
uvicorn api.main:app --port 8000

# Or run everything via Docker
docker compose up
```

### First-time local setup (without running the full scheduler)

The API reads from `data/cityscan_read.duckdb` (a read replica the scheduler maintains). For local dev without the scheduler, after running the pipeline once:

```bash
cp data/cityscan.duckdb data/cityscan_read.duckdb   # seed the read replica
```

### After deploying the access-weighted green patch

Run once on the server after `git pull` + pipeline:

```bash
python scripts/fetch_population.py --wards               # one-time, populates ward_populations.json
python scripts/backfill_green_space_access.py            # locks historical rows to stable values
cp data/cityscan.duckdb data/cityscan_read.duckdb        # refresh read replica (or let scheduler do it)
```

The backfill prevents a one-off NULL→value step on the Organ History chart for `green_space_access_score`. Green space is a yearly static signal — re-run `fetch_green_space.py` + the backfill whenever GLA releases a new year of Green Cover data.

## What works now

| Component | Status |
|-----------|--------|
| Data pipeline (7 sources → Bronze → Silver → Gold) | **Working** |
| FastAPI (15 endpoints: health, scores, boroughs, trends, deprivation, housing affordability, health index, transit access, score quality, agent, bulletin, internal) | **Working** |
| Agent tools (5 curated + `run_sql` + `search_scores` + `get_deprivation` + `get_score_quality` + `get_housing_affordability` + `get_health_index` + `get_transit_access`) | **Working** |
| ChromaDB embedding (gold → vector store) | **Working** |
| pytest test suite (`pytest tests/`) | **Working** |
| Doctor Agent (LangGraph ReAct + SSE streaming + 11 tools) | **Working** |
| Bulletin Agent (LangChain prompt chain + Signal of the Day) | **Working** |
| IMD deprivation context (7 domains per borough) | **Working** |
| Scheduler (APScheduler) | **Working** |
| MCP Server | **Working** |
| Frontend (Next.js) | **Working** |

**API endpoints** (interactive docs at `http://localhost:8000/docs`):
- `GET /health` — service liveness
- `GET /london/score` — city-wide health score
- `GET /boroughs` — all 33 boroughs ranked
- `GET /borough/{name}` — single borough (accepts name or ONS code)
- `GET /borough/{name}/trend` — score history
- `POST /agent/query` — Doctor Agent, SSE stream (`text/event-stream`)
- `GET /bulletin/latest` — latest bulletin markdown
- `POST /bulletin/generate` — trigger bulletin generation
- `GET /boroughs/deprivation` — IMD 2025 deprivation data + 7 sub-domain ranks for all boroughs
- `GET /boroughs/housing-affordability` — ONS Table 5c median ratio + 5-year average for all boroughs
- `GET /boroughs/health-index` — ONS Health Index 2021 for 32 boroughs (City of London excluded by ONS)
- `GET /boroughs/transit-access` — TfL PTAL 2015 borough averages (band 1a–6b, AvPTAI, normalised 0–100)
- `GET /boroughs/score-quality` — per-organ score quality flag (green/amber/red) and 95% bootstrap CI per borough
- `GET /boroughs/trends` — 7-day composite trend direction for all boroughs
- `POST /internal/reset-db` — release DuckDB read connection (internal)

## Architecture

```
Bronze (raw JSON) → Silver (DuckDB, normalised) → Gold (DuckDB, scored + ChromaDB, embedded)
```

See `PRD.md` for full spec and `docs/lineage.md` for data lineage.
