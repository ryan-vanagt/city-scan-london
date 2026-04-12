# Data Lineage

## Pipeline flow

```mermaid
flowchart TD
    OQ[OpenAQ API] -->|hourly| B_OQ[bronze/openaq/]
    TFL[TfL API] -->|hourly| B_TFL[bronze/tfl/]
    RD[Reddit public JSON API] -->|hourly| B_RD[bronze/reddit/]
    GD[Guardian API] -->|hourly| B_GD[bronze/guardian/]
    BBC[BBC News RSS] -->|hourly| B_BBC[bronze/bbc/]
    MP[Met Police API] -->|"daily (data updates monthly)"| B_MP[bronze/met_police/]
    NHS[NHS England A&E CSV] -->|"daily (data updates monthly)"| B_NHS[bronze/nhs_ae/]

    B_OQ --> S[Silver layer\nDuckDB: silver_metrics]
    B_TFL --> S
    B_RD -->|sentiment scored locally| SENT[sentiment/scorer.py]
    SENT --> S
    B_GD -->|sentiment scored locally| SENT
    B_BBC -->|sentiment scored locally| SENT
    B_MP --> S
    B_NHS --> S

    S --> G[Gold layer\nDuckDB: gold_scores]
    G --> CH[ChromaDB\nembeddings]

    G --> TOOLS[Agent Tools\n4 curated + run_sql\n+ search_scores]
    CH --> TOOLS

    %% Access layers — FastAPI and MCP Server both use Agent Tools
    G -->|direct read| API[FastAPI]
    API -->|"/agent/query (SSE)"| DA[Doctor Agent\nLangGraph]
    API -->|"/bulletin/generate"| BA[Bulletin Agent\nLangChain]
    DA --> TOOLS
    BA --> TOOLS
    MCP[MCP Server] --> TOOLS

    %% Frontend communicates via FastAPI only
    FE[Frontend\nNext.js] -->|"HTTP /boroughs, /london/score"| API
    FE -->|"POST /agent/query"| API
    FE -->|"GET /bulletin/latest"| API

    %% Logging
    DA --> LOGS[agent_logs\nagent_logs.duckdb]
    BA --> BLOGS[bulletin_logs\nagent_logs.duckdb]
```



## Lineage fields

Every Silver and Gold record carries:


| Field            | Description                                                                       |
| ---------------- | --------------------------------------------------------------------------------- |
| `source`         | Origin API (`openaq`, `tfl`, `reddit`, `guardian`, `bbc`, `met_police`, `nhs_ae`) |
| `ingested_at`    | UTC timestamp of when the raw data was fetched                                    |
| `pipeline_stage` | `bronze`, `silver`, or `gold`                                                     |


## Retention

| Layer | Retention | Mechanism |
|-------|-----------|-----------|
| Bronze (JSON files) | 1 day | `bronze.cleanup()` after every fetch |
| Silver (DuckDB) | 90 days | `silver_retention` scheduler job at 03:00 UTC |
| Gold (DuckDB) | Forever | Tiny footprint (~290KB/month), needed for long-term trends |
| ChromaDB (embeddings) | Forever | One embedding per borough per day |


## Transformations


| Stage       | File                 | What happens                                                                 |
| ----------- | -------------------- | ---------------------------------------------------------------------------- |
| Bronze      | `pipeline/bronze.py` | Raw API response saved as timestamped JSON — no transformation               |
| Silver      | `pipeline/silver.py` | Parsed, validated, normalised to 0–100 score, mapped to ONS borough code     |
| Gold        | `pipeline/gold.py`   | Per-borough weighted average across all four signals (48h time-bound on silver data); embedded into ChromaDB |
| Embed       | `pipeline/embed.py`  | Gold rows converted to text descriptions and upserted into ChromaDB for RAG  |
| Agent Tools | `agents/tools/`      | 4 curated DuckDB queries + 1 guarded `run_sql` (9-layer security) + 1 RAG `search_scores` |


