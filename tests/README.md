# tests/

Pytest test suite for the CityScan London backend.

## Running tests

```bash
# Run all tests (excluding network and API-key dependent)
pytest tests/ -m "not network and not api_key and not slow"

# Run all tests including API-key dependent ones
pytest tests/ -m "not network"

# Run everything (including network and API-key tests)
pytest tests/

# Run specific test file
pytest tests/test_schemas.py -v

# Verbose output
pytest tests/ -v
```

## Known issues

- `test_pipeline_chain_completes_with_bronze_data` fails when run after other tests due to a DuckDB connection conflict — earlier tests hold a connection to `cityscan.duckdb` and the scheduler test tries to reconnect with different config. Passes in isolation (`pytest tests/test_scheduler.py::test_pipeline_chain_completes_with_bronze_data -x`). Fix requires closing the shared DuckDB connection in test fixture teardown.

## Markers

| Marker | Meaning |
|---|---|
| `slow` | Tests that load the ML sentiment model (>10 s) |
| `network` | Tests that require external network access (postcodes.io, TfL, NHS) |
| `api_key` | Tests that require `ANTHROPIC_API_KEY` in `.env` |

## Test files

### Pipeline tests

| File | What it tests |
|---|---|
| `test_schemas.py` | Borough lookup table, DuckDB schema DDL, coord_to_borough landmarks |
| `test_bronze.py` | `bronze.save()`, `cleanup()`, file existence |
| `test_silver_transforms.py` | Silver normalisation, score clamping, borough coverage per source |
| `test_gold.py` | Gold aggregation, composite score weights, 48h time-bound |
| `test_sentiment.py` | Sentiment scorer output range, batching, positive > negative |
| `test_imd.py` | IMD 2025 borough JSON shape — 33 codes, 7 domains per borough, valid ranks |

### Reference / overlay dataset tests

| File | What it tests |
|---|---|
| `test_housing_affordability.py` | ONS Table 5c JSON shape — 33 boroughs, plausible ratio range, K&C top |
| `test_health_index.py` | ONS Health Index JSON — 32 boroughs (CoL excluded), Richmond top, plausible 70–130 range |
| `test_score_quality.py` | Bootstrap output shape — flag distribution, static-organ rules (sentiment amber, GLA-static green), CI present for green bootstrappable organs, composite flag derivation |

### Agent tool tests

| File | What it tests |
|---|---|
| `test_tools.py` | All 6 agent tools + `run_sql` guardrails (SQL injection, file-read blocking) |
| `test_embed.py` | ChromaDB embedding write + `search_scores` RAG retrieval |

### Integration tests

| File | What it tests |
|---|---|
| `test_api.py` | All FastAPI endpoints against a live uvicorn server |
| `test_doctor.py` | Doctor Agent SSE streaming + `agent_logs` verification |
| `test_bulletin.py` | Bulletin generation + file saving + `bulletin_logs` |
| `test_mcp.py` | MCP server JSON-RPC over Streamable HTTP |

### Utility tests

| File | What it tests |
|---|---|
| `test_db_singleton.py` | Lazy DuckDB singleton connection (read-only, reuse, close) |
| `test_logging_db.py` | Agent and bulletin log table creation, insert, serialization |
| `test_retry.py` | Retry decorator backoff, max attempts, exception propagation |

### Scheduler tests

| File | What it tests |
|---|---|
| `test_scheduler.py` | APScheduler job registration, source groups, error isolation |

### Network-dependent tests

| File | What it tests |
|---|---|
| `test_geo_mappings.py` | Borough centroid geocoding, TfL line mapping, NHS trust lookup |
