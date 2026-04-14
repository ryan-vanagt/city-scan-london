# CityScan London

London is a living organism. CityScan diagnoses its health — and will soon prescribe treatments.

## The Problem

Urban environmental and social health varies dramatically across London's 33 boroughs — but policymakers lack an integrated, real-time view. Air quality, transport disruption, public sentiment, crime, and A&E pressure are all monitored in siloes. No single tool lets you ask "which borough needs the most urgent help and why?"

SDG 11 (Sustainable Cities and Communities) sets targets for air quality (11.6), transport (11.2), green spaces (11.7), and inclusive planning (11.3/11.9) — CityScan brings them together.

## What CityScan Does

CityScan models London as a human body. Each biological system draws from public data sources, producing a real-time health score (0-100) per borough. A natural language "City Doctor" agent answers cross-domain questions no single data source can. A daily bulletin summarises the city's vital signs.

### Live now

| Organ | Data Source | SDG 11 Target | Signal |
|---|---|---|---|
| 🫁 Lungs | OpenAQ | 11.6 — Air quality | PM2.5, NO2 per station |
| 🩸 Arteries | TfL API | 11.2 — Transport | Tube line status & severity |
| 🧠 Brain | Reddit + Guardian + BBC | — | Public sentiment (NLP) |
| 🛡️ Immune | Met Police + NHS A&E | — | Per-capita crime (ONS population, winsorised) + A&E pressure |

### Building now (target: April 16)

| Organ / Feature | Data Source | SDG 11 Target | What it adds |
|---|---|---|---|
| 🌿 Skin | London Datastore | 11.7 — Green spaces | Green space coverage per borough |
| Prescriptive layer | Evidence-based policy menu | 11.9 — Policies for inclusion | Doctor + Bulletin recommend treatments, not just diagnose |
| Deprivation context | MHCLG IMD data | 11.3 — Inclusive urbanisation | Equity-aware prescriptions targeting vulnerable boroughs |

See [`docs/competition/roadmap.md`](docs/competition/roadmap.md) for full implementation plan.

## Key Features

**Working:**
- **Thermal borough map** — 33 boroughs coloured by health score (red = critical, blue = healthy), with medical scan landing animation
- **City Doctor** — Natural language agent (LangGraph ReAct) that diagnoses London's health using 6 tools + RAG
- **Daily Bulletin** — LLM-generated health report with source attribution
- **MCP Server** — All tools exposed via Model Context Protocol for external agent integration
- **Real-time pipeline** — Hourly data refresh, automated scoring, ChromaDB embeddings

**Coming:**
- **Evidence-based prescriptions** — Constrained intervention menu grounded in real London policy documents (not LLM speculation)
- **Green space organ** — 5th biological system (SDG 11.7)
- **Deprivation overlay** — IMD context for equity-aware interventions

<!-- TODO: Add screenshot/GIF of thermal map -->

## SDG 11 Alignment

| Target | Description | CityScan Coverage | Status |
|--------|-------------|-------------------|--------|
| **11.6** | Reduce environmental impact (air quality) | Lungs — PM2.5/NO2 monitoring per borough | Live |
| **11.2** | Sustainable transport systems | Arteries — TfL tube line status scoring | Live |
| **11.7** | Green and public spaces | Skin — green space coverage per borough | Planned |
| **11.3** | Inclusive urbanisation | Deprivation context for equity-aware prescriptions | Planned |
| **11.9** | Policies for inclusion | Evidence-based intervention menu | Planned |

## Stack

Python 3.11 · DuckDB · ChromaDB · LangChain + LangGraph · Claude Haiku · FastAPI · Next.js · Docker

## Quick Start

```bash
cp .env.example .env                        # add your API keys
python scripts/generate_geo_mappings.py      # fetch geographic reference data
docker compose up                            # runs everything (5 services)
```

## API Endpoints

Interactive docs at `http://localhost:8000/docs` (Swagger UI).

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Service liveness |
| GET | `/london/score` | City-wide health score |
| GET | `/boroughs` | All 33 boroughs ranked |
| GET | `/borough/{name}` | Single borough (name or ONS code) |
| GET | `/borough/{name}/trend` | Score history |
| POST | `/agent/query` | Doctor Agent (SSE stream) |
| GET | `/bulletin/latest` | Latest bulletin markdown |
| POST | `/bulletin/generate` | Trigger bulletin generation |

## Architecture

```
Bronze (raw JSON) → Silver (DuckDB, normalised) → Gold (DuckDB, scored + ChromaDB, embedded)
```

See [`PRD.md`](PRD.md) for full spec, [`docs/lineage.md`](docs/lineage.md) for data lineage, [`docs/competition/roadmap.md`](docs/competition/roadmap.md) for competition roadmap.
