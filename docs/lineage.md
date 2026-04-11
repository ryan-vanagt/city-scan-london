# Data Lineage

## Pipeline flow

```mermaid
flowchart TD
    OQ[OpenAQ API] -->|hourly| B_OQ[bronze/openaq/]
    TFL[TfL API] -->|hourly| B_TFL[bronze/tfl/]
    RD[Reddit public JSON API] -->|3h| B_RD[bronze/reddit/]
    GD[Guardian API] -->|3h| B_GD[bronze/guardian/]
    BBC[BBC News RSS] -->|3h| B_BBC[bronze/bbc/]
    MP[Met Police API] -->|monthly| B_MP[bronze/met_police/]
    NHS[NHS England A&E CSV] -->|monthly| B_NHS[bronze/nhs_ae/]

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
    G --> API[FastAPI]
    CH --> TOOLS

    TOOLS --> DA[Doctor Agent\nLangGraph]
    TOOLS --> BA[Bulletin Agent\nLangChain]
    TOOLS --> MCP[MCP Server]
    API --> FE[Frontend\nNext.js]
    DA --> LOGS[DuckDB: agent_logs]
    BA --> BLOGS[DuckDB: bulletin_logs]
```



## Lineage fields

Every Silver and Gold record carries:


| Field            | Description                                                                       |
| ---------------- | --------------------------------------------------------------------------------- |
| `source`         | Origin API (`openaq`, `tfl`, `reddit`, `guardian`, `bbc`, `met_police`, `nhs_ae`) |
| `ingested_at`    | UTC timestamp of when the raw data was fetched                                    |
| `pipeline_stage` | `bronze`, `silver`, or `gold`                                                     |


## Transformations


| Stage       | File                 | What happens                                                                 |
| ----------- | -------------------- | ---------------------------------------------------------------------------- |
| Bronze      | `pipeline/bronze.py` | Raw API response saved as timestamped JSON — no transformation               |
| Silver      | `pipeline/silver.py` | Parsed, validated, normalised to 0–100 score, mapped to ONS borough code     |
| Gold        | `pipeline/gold.py`   | Per-borough weighted average across all four signals; embedded into ChromaDB |
| Embed       | `pipeline/embed.py`  | Gold rows converted to text descriptions and upserted into ChromaDB for RAG  |
| Agent Tools | `agents/tools/`      | 4 curated DuckDB queries + 1 guarded `run_sql` + 1 RAG `search_scores`       |


