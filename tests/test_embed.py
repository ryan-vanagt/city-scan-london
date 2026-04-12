"""Test pipeline/embed.py + agents/tools/rag_query.py — ChromaDB embedding and retrieval.

Tests use in-memory ChromaDB (chromadb.Client()) + in-memory DuckDB.
Requires chromadb to be installed: pip install chromadb
"""

import duckdb
import pytest

chromadb = pytest.importorskip("chromadb")

from pipeline.embed import (
    _format_score,
    _row_to_document,
    _row_to_id,
    _row_to_metadata,
    embed_gold_scores,
)
from pipeline.schemas import init_db


# ---------------------------------------------------------------------------
# Helper — plain function, not a fixture
# ---------------------------------------------------------------------------

def insert_gold(
    con: duckdb.DuckDBPyConnection,
    borough_code: str,
    borough_name: str,
    air: float | None = None,
    transit: float | None = None,
    sentiment: float | None = None,
    immune: float | None = None,
    composite: float = 50.0,
    timestamp: str = "2026-04-09T12:00:00+00:00",
    ingested_at: str = "2026-04-09T12:00:00+00:00",
) -> None:
    """Insert a single gold_scores row for testing."""
    con.execute(
        """
        INSERT INTO gold_scores
        (borough_code, borough_name, timestamp, air_score, transit_score,
         sentiment_score, immune_score, composite_score, ingested_at, pipeline_stage)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            borough_code, borough_name, timestamp, air, transit,
            sentiment, immune, composite, ingested_at, "gold",
        ],
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def in_memory_chroma():
    """Set up an in-memory ChromaDB client patched into both write and read paths."""
    import pipeline.chroma_client as pipeline_cc
    import agents.tools.chroma_client as agent_cc

    client = chromadb.Client()

    # Save originals so we can restore after the test
    orig_pipeline_client = pipeline_cc._client
    orig_agent_client = agent_cc._client
    orig_pipeline_get = pipeline_cc.get_client
    orig_agent_get = agent_cc.get_client

    # Patch both sides to the same in-memory client
    pipeline_cc._client = client
    agent_cc._client = client

    yield client

    # Delete test collection so next test starts clean
    try:
        client.delete_collection("gold_scores")
    except Exception:
        pass

    # Restore originals
    pipeline_cc._client = orig_pipeline_client
    agent_cc._client = orig_agent_client
    pipeline_cc.get_client = orig_pipeline_get
    agent_cc.get_client = orig_agent_get


@pytest.fixture
def sample_row():
    """A fully-populated gold_scores row tuple."""
    return ("E09000007", "Camden", "2026-04-10T12:00:00+00:00", 34.2, 82.0, 61.5, 55.6, 58.3)


@pytest.fixture
def sample_row_nulls():
    """A gold_scores row tuple with NULL air and transit scores."""
    return ("E09000006", "Bromley", "2026-04-10T12:00:00+00:00", None, None, 43.5, 71.2, 62.5)


# ===========================================================================
# _format_score
# ===========================================================================

def test_format_score_value():
    assert _format_score(34.2) == "34.20"


def test_format_score_none():
    assert _format_score(None) == "N/A"


def test_format_score_zero():
    assert _format_score(0.0) == "0.00"


def test_format_score_hundred():
    assert _format_score(100.0) == "100.00"


# ===========================================================================
# _row_to_document
# ===========================================================================

def test_row_to_document_contains_borough_name(sample_row):
    assert "Camden" in _row_to_document(sample_row)


def test_row_to_document_contains_ons_code(sample_row):
    assert "E09000007" in _row_to_document(sample_row)


def test_row_to_document_contains_date(sample_row):
    assert "2026-04-10" in _row_to_document(sample_row)


def test_row_to_document_contains_composite(sample_row):
    assert "58.30" in _row_to_document(sample_row)


def test_row_to_document_contains_air_score(sample_row):
    assert "34.20" in _row_to_document(sample_row)


def test_row_to_document_null_air_is_na(sample_row_nulls):
    assert "Air: N/A" in _row_to_document(sample_row_nulls)


def test_row_to_document_null_transit_is_na(sample_row_nulls):
    assert "Transit: N/A" in _row_to_document(sample_row_nulls)


def test_row_to_document_null_row_sentiment_has_value(sample_row_nulls):
    assert "43.50" in _row_to_document(sample_row_nulls)


# ===========================================================================
# _row_to_id
# ===========================================================================

def test_row_to_id_correct_format(sample_row):
    assert _row_to_id(sample_row) == "E09000007_2026-04-10"


# ===========================================================================
# _row_to_metadata
# ===========================================================================

def test_row_to_metadata_has_borough_code(sample_row):
    assert _row_to_metadata(sample_row)["borough_code"] == "E09000007"


def test_row_to_metadata_has_borough_name(sample_row):
    assert _row_to_metadata(sample_row)["borough_name"] == "Camden"


def test_row_to_metadata_has_timestamp(sample_row):
    assert _row_to_metadata(sample_row)["timestamp"] == "2026-04-10"


def test_row_to_metadata_has_composite_score(sample_row):
    assert _row_to_metadata(sample_row)["composite_score"] == pytest.approx(58.3)


def test_row_to_metadata_has_air_score(sample_row):
    assert _row_to_metadata(sample_row)["air_score"] == pytest.approx(34.2)


def test_row_to_metadata_null_omits_air_score(sample_row_nulls):
    assert "air_score" not in _row_to_metadata(sample_row_nulls)


def test_row_to_metadata_null_omits_transit_score(sample_row_nulls):
    assert "transit_score" not in _row_to_metadata(sample_row_nulls)


def test_row_to_metadata_null_has_sentiment_score(sample_row_nulls):
    assert _row_to_metadata(sample_row_nulls)["sentiment_score"] == pytest.approx(43.5)


def test_row_to_metadata_null_has_immune_score(sample_row_nulls):
    assert _row_to_metadata(sample_row_nulls)["immune_score"] == pytest.approx(71.2)


# ===========================================================================
# embed_gold_scores — in-memory ChromaDB
# ===========================================================================

def test_embed_returns_correct_count(fresh_db, in_memory_chroma):
    insert_gold(
        fresh_db, "E09000007", "Camden",
        air=34.2, transit=82.0, sentiment=61.5, immune=55.6, composite=58.3,
    )
    insert_gold(
        fresh_db, "E09000001", "City of London",
        air=80.0, transit=90.0, sentiment=70.0, immune=85.0, composite=81.0,
    )
    assert embed_gold_scores(fresh_db) == 2


def test_embed_collection_has_correct_doc_count(fresh_db, in_memory_chroma):
    import pipeline.chroma_client as cc
    insert_gold(
        fresh_db, "E09000007", "Camden",
        air=34.2, transit=82.0, sentiment=61.5, immune=55.6, composite=58.3,
    )
    insert_gold(
        fresh_db, "E09000001", "City of London",
        air=80.0, transit=90.0, sentiment=70.0, immune=85.0, composite=81.0,
    )
    embed_gold_scores(fresh_db)
    all_docs = cc.get_collection().get()
    assert len(all_docs["ids"]) == 2


def test_embed_ids_are_correct_format(fresh_db, in_memory_chroma):
    import pipeline.chroma_client as cc
    insert_gold(
        fresh_db, "E09000007", "Camden",
        air=34.2, transit=82.0, sentiment=61.5, immune=55.6, composite=58.3,
    )
    insert_gold(
        fresh_db, "E09000001", "City of London",
        air=80.0, transit=90.0, sentiment=70.0, immune=85.0, composite=81.0,
    )
    embed_gold_scores(fresh_db)
    all_docs = cc.get_collection().get()
    assert any("E09000007_" in doc_id for doc_id in all_docs["ids"])


def test_embed_camden_doc_contains_name(fresh_db, in_memory_chroma):
    import pipeline.chroma_client as cc
    insert_gold(
        fresh_db, "E09000007", "Camden",
        air=34.2, transit=82.0, sentiment=61.5, immune=55.6, composite=58.3,
    )
    insert_gold(
        fresh_db, "E09000001", "City of London",
        air=80.0, transit=90.0, sentiment=70.0, immune=85.0, composite=81.0,
    )
    embed_gold_scores(fresh_db)
    all_docs = cc.get_collection().get()
    for i, doc_id in enumerate(all_docs["ids"]):
        if "E09000007" in doc_id:
            assert "Camden" in all_docs["documents"][i]
            break


def test_embed_camden_doc_contains_composite(fresh_db, in_memory_chroma):
    import pipeline.chroma_client as cc
    insert_gold(
        fresh_db, "E09000007", "Camden",
        air=34.2, transit=82.0, sentiment=61.5, immune=55.6, composite=58.3,
    )
    insert_gold(
        fresh_db, "E09000001", "City of London",
        air=80.0, transit=90.0, sentiment=70.0, immune=85.0, composite=81.0,
    )
    embed_gold_scores(fresh_db)
    all_docs = cc.get_collection().get()
    for i, doc_id in enumerate(all_docs["ids"]):
        if "E09000007" in doc_id:
            assert "58.30" in all_docs["documents"][i]
            break


def test_embed_metadata_borough_code(fresh_db, in_memory_chroma):
    import pipeline.chroma_client as cc
    insert_gold(
        fresh_db, "E09000007", "Camden",
        air=34.2, transit=82.0, sentiment=61.5, immune=55.6, composite=58.3,
    )
    insert_gold(
        fresh_db, "E09000001", "City of London",
        air=80.0, transit=90.0, sentiment=70.0, immune=85.0, composite=81.0,
    )
    embed_gold_scores(fresh_db)
    all_docs = cc.get_collection().get()
    for i, doc_id in enumerate(all_docs["ids"]):
        if "E09000007" in doc_id:
            assert all_docs["metadatas"][i]["borough_code"] == "E09000007"
            break


def test_embed_metadata_composite_score(fresh_db, in_memory_chroma):
    import pipeline.chroma_client as cc
    insert_gold(
        fresh_db, "E09000007", "Camden",
        air=34.2, transit=82.0, sentiment=61.5, immune=55.6, composite=58.3,
    )
    insert_gold(
        fresh_db, "E09000001", "City of London",
        air=80.0, transit=90.0, sentiment=70.0, immune=85.0, composite=81.0,
    )
    embed_gold_scores(fresh_db)
    all_docs = cc.get_collection().get()
    for i, doc_id in enumerate(all_docs["ids"]):
        if "E09000007" in doc_id:
            assert all_docs["metadatas"][i]["composite_score"] == pytest.approx(58.3)
            break


# ===========================================================================
# Upsert deduplication
# ===========================================================================

def test_re_embed_returns_same_count(fresh_db, in_memory_chroma):
    insert_gold(
        fresh_db, "E09000007", "Camden",
        air=34.2, transit=82.0, sentiment=61.5, immune=55.6, composite=58.3,
    )
    insert_gold(
        fresh_db, "E09000001", "City of London",
        air=80.0, transit=90.0, sentiment=70.0, immune=85.0, composite=81.0,
    )
    embed_gold_scores(fresh_db)
    assert embed_gold_scores(fresh_db) == 2


def test_re_embed_no_duplication(fresh_db, in_memory_chroma):
    import pipeline.chroma_client as cc
    insert_gold(
        fresh_db, "E09000007", "Camden",
        air=34.2, transit=82.0, sentiment=61.5, immune=55.6, composite=58.3,
    )
    insert_gold(
        fresh_db, "E09000001", "City of London",
        air=80.0, transit=90.0, sentiment=70.0, immune=85.0, composite=81.0,
    )
    embed_gold_scores(fresh_db)
    embed_gold_scores(fresh_db)
    all_docs = cc.get_collection().get()
    assert len(all_docs["ids"]) == 2


def test_updated_embed_overwrites_doc(fresh_db, in_memory_chroma):
    import pipeline.chroma_client as cc
    insert_gold(
        fresh_db, "E09000007", "Camden",
        air=34.2, transit=82.0, sentiment=61.5, immune=55.6, composite=58.3,
    )
    insert_gold(
        fresh_db, "E09000001", "City of London",
        air=80.0, transit=90.0, sentiment=70.0, immune=85.0, composite=81.0,
    )
    embed_gold_scores(fresh_db)
    # Insert updated Camden row with same timestamp date (same ID) but higher composite
    fresh_db.execute(
        """
        INSERT INTO gold_scores
        (borough_code, borough_name, timestamp, air_score, transit_score,
         sentiment_score, immune_score, composite_score, ingested_at, pipeline_stage)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            "E09000007", "Camden", "2026-04-09T14:00:00+00:00", 50.0, 82.0,
            61.5, 55.6, 62.3, "2026-04-09T14:00:00+00:00", "gold",
        ],
    )
    embed_gold_scores(fresh_db)
    all_docs = cc.get_collection().get()
    for i, doc_id in enumerate(all_docs["ids"]):
        if "E09000007" in doc_id:
            assert "62.30" in all_docs["documents"][i]
            break


def test_updated_embed_doc_count_unchanged(fresh_db, in_memory_chroma):
    import pipeline.chroma_client as cc
    insert_gold(
        fresh_db, "E09000007", "Camden",
        air=34.2, transit=82.0, sentiment=61.5, immune=55.6, composite=58.3,
    )
    insert_gold(
        fresh_db, "E09000001", "City of London",
        air=80.0, transit=90.0, sentiment=70.0, immune=85.0, composite=81.0,
    )
    embed_gold_scores(fresh_db)
    fresh_db.execute(
        """
        INSERT INTO gold_scores
        (borough_code, borough_name, timestamp, air_score, transit_score,
         sentiment_score, immune_score, composite_score, ingested_at, pipeline_stage)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            "E09000007", "Camden", "2026-04-09T14:00:00+00:00", 50.0, 82.0,
            61.5, 55.6, 62.3, "2026-04-09T14:00:00+00:00", "gold",
        ],
    )
    assert embed_gold_scores(fresh_db) == 2
    all_docs = cc.get_collection().get()
    assert len(all_docs["ids"]) == 2


# ===========================================================================
# Empty gold_scores
# ===========================================================================

def test_embed_empty_gold_returns_zero(fresh_db, in_memory_chroma):
    assert embed_gold_scores(fresh_db) == 0


# ===========================================================================
# NULL score handling in embedding
# ===========================================================================

def test_null_embed_returns_one(fresh_db, in_memory_chroma):
    insert_gold(
        fresh_db, "E09000006", "Bromley",
        air=None, transit=None, sentiment=43.5, immune=71.2, composite=62.5,
    )
    assert embed_gold_scores(fresh_db) == 1


def test_null_embed_doc_air_is_na(fresh_db, in_memory_chroma):
    import pipeline.chroma_client as cc
    insert_gold(
        fresh_db, "E09000006", "Bromley",
        air=None, transit=None, sentiment=43.5, immune=71.2, composite=62.5,
    )
    embed_gold_scores(fresh_db)
    docs = cc.get_collection().get()
    assert "Air: N/A" in docs["documents"][0]


def test_null_embed_doc_transit_is_na(fresh_db, in_memory_chroma):
    import pipeline.chroma_client as cc
    insert_gold(
        fresh_db, "E09000006", "Bromley",
        air=None, transit=None, sentiment=43.5, immune=71.2, composite=62.5,
    )
    embed_gold_scores(fresh_db)
    docs = cc.get_collection().get()
    assert "Transit: N/A" in docs["documents"][0]


def test_null_embed_metadata_no_air_score(fresh_db, in_memory_chroma):
    import pipeline.chroma_client as cc
    insert_gold(
        fresh_db, "E09000006", "Bromley",
        air=None, transit=None, sentiment=43.5, immune=71.2, composite=62.5,
    )
    embed_gold_scores(fresh_db)
    docs = cc.get_collection().get()
    assert "air_score" not in docs["metadatas"][0]


def test_null_embed_metadata_has_sentiment_score(fresh_db, in_memory_chroma):
    import pipeline.chroma_client as cc
    insert_gold(
        fresh_db, "E09000006", "Bromley",
        air=None, transit=None, sentiment=43.5, immune=71.2, composite=62.5,
    )
    embed_gold_scores(fresh_db)
    docs = cc.get_collection().get()
    assert docs["metadatas"][0]["sentiment_score"] == pytest.approx(43.5)


# ===========================================================================
# search_scores — RAG retrieval
# ===========================================================================

@pytest.fixture
def rag_db_with_chroma(fresh_db, in_memory_chroma):
    """fresh_db + in_memory_chroma pre-populated with three boroughs for RAG tests."""
    insert_gold(
        fresh_db, "E09000007", "Camden",
        air=34.2, transit=82.0, sentiment=61.5, immune=55.6, composite=58.3,
    )
    insert_gold(
        fresh_db, "E09000001", "City of London",
        air=80.0, transit=90.0, sentiment=70.0, immune=85.0, composite=81.0,
    )
    insert_gold(
        fresh_db, "E09000006", "Bromley",
        air=None, transit=None, sentiment=43.5, immune=71.2, composite=62.5,
    )
    embed_gold_scores(fresh_db)
    return fresh_db


def test_search_scores_returns_results(rag_db_with_chroma):
    from agents.tools.rag_query import search_scores
    result = search_scores("air quality")
    assert result["count"] > 0


def test_search_scores_results_have_document_field(rag_db_with_chroma):
    from agents.tools.rag_query import search_scores
    result = search_scores("air quality")
    assert "document" in result["results"][0]


def test_search_scores_results_have_metadata_field(rag_db_with_chroma):
    from agents.tools.rag_query import search_scores
    result = search_scores("air quality")
    assert "metadata" in result["results"][0]


def test_search_scores_results_have_distance_field(rag_db_with_chroma):
    from agents.tools.rag_query import search_scores
    result = search_scores("air quality")
    assert "distance" in result["results"][0]


def test_search_scores_n_results_limit(rag_db_with_chroma):
    from agents.tools.rag_query import search_scores
    result = search_scores("borough health", n_results=1)
    assert result["count"] == 1


def test_search_scores_borough_filter_returns_results(rag_db_with_chroma):
    from agents.tools.rag_query import search_scores
    result = search_scores("health score", borough_code="E09000007")
    assert result["count"] > 0


def test_search_scores_borough_filter_scoped_to_camden(rag_db_with_chroma):
    from agents.tools.rag_query import search_scores
    result = search_scores("health score", borough_code="E09000007")
    assert all(
        r["metadata"]["borough_code"] == "E09000007"
        for r in result["results"]
    )


def test_search_scores_empty_collection(in_memory_chroma):
    """search_scores on an empty collection returns count=0 without crashing."""
    import agents.tools.chroma_client as agent_cc
    from agents.tools.rag_query import search_scores

    # Ensure the collection exists but is empty
    in_memory_chroma.get_or_create_collection("gold_scores")
    # Point the agent client at this in-memory instance
    agent_cc._client = in_memory_chroma

    result = search_scores("anything")
    assert result["count"] == 0


# ===========================================================================
# Fault tolerance
# ===========================================================================

def test_embed_fault_tolerance_returns_zero(fresh_db, in_memory_chroma):
    """embed_gold_scores returns 0 when ChromaDB get_client raises, not crash."""
    import pipeline.chroma_client as cc

    def broken_get():
        raise ConnectionError("ChromaDB server is down")

    original_get = cc.get_client
    cc._client = None
    cc.get_client = broken_get
    try:
        insert_gold(fresh_db, "E09000007", "Camden", composite=50.0)
        result = embed_gold_scores(fresh_db)
        assert result == 0
    finally:
        cc.get_client = original_get


def test_search_fault_tolerance_returns_error(in_memory_chroma):
    """search_scores returns an error dict when ChromaDB is unavailable."""
    import agents.tools.chroma_client as agent_cc
    from agents.tools.rag_query import search_scores

    def broken_agent_get():
        raise ConnectionError("ChromaDB server is down")

    original_get = agent_cc.get_client
    agent_cc._client = None
    agent_cc.get_client = broken_agent_get
    try:
        result = search_scores("test query")
        assert "error" in result
    finally:
        agent_cc.get_client = original_get


def test_search_fault_tolerance_count_zero(in_memory_chroma):
    """search_scores returns count=0 when ChromaDB is unavailable."""
    import agents.tools.chroma_client as agent_cc
    from agents.tools.rag_query import search_scores

    def broken_agent_get():
        raise ConnectionError("ChromaDB server is down")

    original_get = agent_cc.get_client
    agent_cc._client = None
    agent_cc.get_client = broken_agent_get
    try:
        result = search_scores("test query")
        assert result["count"] == 0
    finally:
        agent_cc.get_client = original_get
