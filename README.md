# CityScan London

A live urban health diagnostic platform that models London as a human body.

Four public data sources map to four biological systems, producing a real-time health score per London borough — queryable via a natural language agent interface and summarised in a daily LLM-generated bulletin.

| System | Data Source | Signal |
|---|---|---|
| 🫁 Lungs | OpenAQ | Air quality (PM2.5, NO2, O3) |
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
docker compose up
```

- API: `http://localhost:8000`
- Frontend: `http://localhost:3000`
- MCP server: `http://localhost:8002`

## Architecture

Bronze (raw JSON) → Silver (DuckDB, normalised) → Gold (DuckDB, scored + ChromaDB, embedded)

See `PRD.md` for full spec and `docs/lineage.md` for data lineage diagram.
