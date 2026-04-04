# Data Lineage

## Pipeline flow

```mermaid
flowchart TD
    OQ[OpenAQ API] -->|hourly| B_OQ[bronze/openaq/]
    TFL[TfL API] -->|hourly| B_TFL[bronze/tfl/]
    RD[Reddit PRAW] -->|3h| B_RD[bronze/reddit/]
    GD[Guardian API] -->|3h| B_GD[bronze/guardian/]
    MP[Met Police API] -->|monthly| B_MP[bronze/met_police/]

    B_OQ --> S[Silver layer\nDuckDB: silver_metrics]
    B_TFL --> S
    B_RD -->|sentiment scored locally| SENT[sentiment/scorer.py]
    SENT --> S
    B_GD -->|sentiment scored locally| SENT
    B_MP --> S

    S --> G[Gold layer\nDuckDB: gold_scores]
    G --> CH[ChromaDB\nembeddings]

    G --> API[FastAPI]
    CH --> API
    API --> DA[Doctor Agent\nLangGraph]
    API --> BA[Bulletin Agent\nLangChain]
    DA --> LOGS[DuckDB: agent_logs]
    BA --> BLOGS[DuckDB: bulletin_logs]
```

## Lineage fields

Every Silver and Gold record carries:

| Field | Description |
|---|---|
| `source` | Origin API (`openaq`, `tfl`, `reddit`, `guardian`, `met_police`) |
| `ingested_at` | UTC timestamp of when the raw data was fetched |
| `pipeline_stage` | `bronze`, `silver`, or `gold` |

## Transformations

| Stage | File | What happens |
|---|---|---|
| Bronze | `pipeline/bronze.py` | Raw API response saved as timestamped JSON — no transformation |
| Silver | `pipeline/silver.py` | Parsed, validated, normalised to 0–100 score, mapped to ONS borough code |
| Gold | `pipeline/gold.py` | Per-borough weighted average across all four signals; embedded into ChromaDB |
