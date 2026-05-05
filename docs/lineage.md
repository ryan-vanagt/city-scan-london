# Data Lineage

## Pipeline flow

```mermaid
flowchart TD
    OQ[OpenAQ API] -->|hourly| B_OQ[bronze/openaq/]
    TFL[TfL API] -->|hourly| B_TFL[bronze/tfl/]
    RD[Reddit public JSON API] -.->|"hourly (currently 403 blocked)"| B_RD[bronze/reddit/]
    GD[Guardian API] -->|hourly| B_GD[bronze/guardian/]
    BBC[BBC News RSS] -->|hourly| B_BBC[bronze/bbc/]
    MP[Met Police API] -->|"daily (data updates monthly)"| B_MP[bronze/met_police/]
    NHS[NHS England A&E CSV] -->|"daily (data updates monthly)"| B_NHS[bronze/nhs_ae/]
    GS[GLA Green Cover 2024] -->|"daily (static yearly data)"| B_GS[data/static/green_space.json]
    LAEI[GLA LAEI 2022<br>modelled air quality] -->|"daily (static yearly data)"| B_LAEI[data/static/laei_air_quality.json]
    WP[ONS Nomis NM_2014_1<br>ward populations] -.->|static join at silver| S
    HOUSE[ONS Housing Affordability Ratio 2025<br>Table 5c, annual] -->|"manual refresh"| B_HOUSE[data/static/housing_affordability.json]
    HI[ONS Health Index for England 2021<br>Table 2, annual] -->|"manual refresh"| B_HI[data/static/ons_health_index.json]
    PTAL[TfL PTAL 2015<br>borough averages] -->|"manual refresh on TfL re-publication"| B_PTAL[data/static/transit_access.json]
    SQ[Bootstrap of gold time-series<br>1000 resamples per borough/organ] -->|"periodic (re-run after gold refresh)"| B_SQ[data/static/score_quality.json]

    B_OQ --> S[Silver layer\nDuckDB: silver_metrics]
    B_TFL --> S
    B_RD -->|sentiment scored locally| SENT[sentiment/scorer.py]
    SENT --> S
    B_GD -->|sentiment scored locally| SENT
    B_BBC -->|sentiment scored locally| SENT
    B_MP --> S
    B_NHS --> S
    B_GS --> S
    B_LAEI --> S

    S --> G[Gold layer\nDuckDB: gold_scores]
    G --> CH[ChromaDB\nembeddings]

    B_OQ --> SD[Silver Detail\nDuckDB: silver_detail]
    B_TFL --> SD
    B_MP --> SD
    B_NHS --> SD
    B_GS -->|ward-level detail| SD
    B_RD -->|sentiment per title| SH[Silver Headlines\nDuckDB: silver_headlines]
    B_GD -->|sentiment per title| SH
    B_BBC -->|sentiment per title| SH

    G --> TOOLS[Agent Tools\n4 curated DB + run_sql\n+ search_scores\n+ deprivation/score_quality/\nhousing_affordability/\nhealth_index/transit_access]
    SD --> TOOLS
    SH --> TOOLS
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
    B_HOUSE -->|"GET /boroughs/housing-affordability"| API
    B_HI -->|"GET /boroughs/health-index"| API
    B_SQ -->|"GET /boroughs/score-quality"| API

    %% Logging
    DA --> LOGS[agent_logs\nagent_logs.duckdb]
    BA --> BLOGS[bulletin_logs\nagent_logs.duckdb]
```



## Lineage fields

Every Silver and Gold record carries:


| Field            | Description                                                                       |
| ---------------- | --------------------------------------------------------------------------------- |
| `source`         | Origin API (`openaq`, `tfl`, `reddit`, `guardian`, `bbc`, `met_police`, `nhs_ae`, `green_space`, `laei`). External reference / overlay datasets (`housing_affordability`, `ons_health_index`, `score_quality`, `transit_access`, `imd`) live in `data/static/` and are served directly via the API rather than passing through the bronze→silver→gold pipeline. |
| `ingested_at`    | UTC timestamp of when the raw data was fetched                                    |
| `pipeline_stage` | `bronze`, `silver`, or `gold`                                                     |


## Retention

| Layer | Retention | Mechanism |
|-------|-----------|-----------|
| Bronze (JSON files) | 1 day | `bronze.cleanup()` after every fetch |
| Silver (DuckDB: silver_metrics) | 90 days | `silver_retention` scheduler job at 03:00 UTC |
| Silver Detail (DuckDB: silver_detail, silver_headlines) | 90 days | Same retention job |
| Gold (DuckDB) | Forever | Tiny footprint (~290KB/month), needed for long-term trends |
| ChromaDB (embeddings) | Forever | One embedding per borough per day |


## Transformations


| Stage       | File                 | What happens                                                                 |
| ----------- | -------------------- | ---------------------------------------------------------------------------- |
| Bronze      | `pipeline/bronze.py` | Raw API response saved as timestamped JSON — no transformation               |
| Silver      | `pipeline/silver.py` | Parsed, validated, normalised to 0–100 score, mapped to ONS borough code. Green space emits TWO metrics per borough: `green_space` (raw coverage) + `green_space_access` (ward-population-weighted, joins `data/static/ward_populations.json`). LAEI emits `air_quality_modelled` per borough (population-weighted PM2.5/NO2 annual mean, WHO-ratio exponential decay matching the live OpenAQ transform for comparability). Crime per-capita is log-transformed (`log(1 + rate)`) before min-max normalisation so one extreme borough does not flatten the rest of the distribution. |
| Silver Detail | `pipeline/silver.py` | Per-item context (crime categories, tube line statuses, AQ station readings, NHS trust data, ward-level green space coverage, per-headline sentiment) — does NOT feed into gold scores |
| Gold        | `pipeline/gold.py`   | Per-borough weighted average across five organ signals (48h time-bound on silver data); embedded into ChromaDB. Composite uses RAW `green_space_score`, not the access-weighted variant, to keep the headline score stable for historical comparison and equity-residual work. Both green columns are persisted. |
| Embed       | `pipeline/embed.py`  | Gold rows converted to text descriptions and upserted into ChromaDB for RAG  |
| Agent Tools | `agents/tools/`      | 4 curated DuckDB queries + 1 guarded `run_sql` (13-layer security) + 1 RAG `search_scores` + 5 static-JSON overlays (deprivation, score_quality, housing_affordability, health_index, transit_access) |


