# CityScan London

A live urban health diagnostic platform that models London as a human body.

Four public data sources map to four biological systems, producing a real-time health score per London borough — queryable via a natural language agent interface and summarised in a daily LLM-generated bulletin.

| System | Data Source | Signal |
|---|---|---|
| 🫁 Lungs | OpenAQ | Air quality (PM2.5, NO2) |
| 🩸 Arteries | TfL API | Tube line status & severity scores |
| 🧠 Brain | Reddit + Guardian + BBC News | Public sentiment (NLP) |
| 🛡️ Immune system | Met Police API + NHS England A&E | Crime by borough + A&E pressure |

## Stack

Python · DuckDB · ChromaDB · LangChain + LangGraph · FastAPI · Next.js · Docker

## Setup

```bash
cp .env.example .env   # add your API keys
python scripts/generate_geo_mappings.py   # fetch borough/TfL/NHS geographic data
```

## Run

```bash
# Run the data pipeline (fetches live data → scores all 33 boroughs)
python ingestion/run_pipeline.py

# Start the API
uvicorn api.main:app --port 8000

# Or run everything via Docker
docker compose up
```

## What works now

| Component | Status |
|-----------|--------|
| Data pipeline (7 sources → Bronze → Silver → Gold) | **Working** |
| FastAPI (8 endpoints: health, scores, boroughs, trends, agent, bulletin) | **Working** |
| Agent tools (4 curated + `run_sql` + `search_scores`) | **Working** |
| ChromaDB embedding (gold → vector store) | **Working** |
| pytest test suite (`pytest tests/`) | **Working** |
| Doctor Agent (LangGraph ReAct + SSE streaming + tools + RAG) | **Working** |
| Bulletin Agent (LangChain prompt chain) | **Working** |
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

## Architecture

Bronze (raw JSON) → Silver (DuckDB, normalised) → Gold (DuckDB, scored + ChromaDB, embedded)

See `PRD.md` for full spec and `docs/lineage.md` for data lineage.
