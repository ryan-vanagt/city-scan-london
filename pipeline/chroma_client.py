"""
ChromaDB client for the ingestion pipeline (write side).

Connects to ChromaDB server via HTTP when CHROMADB_HOST is set (Docker),
falls back to a local PersistentClient for development without Docker.
"""

import logging
import os
import threading
from pathlib import Path

import chromadb

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PERSIST_DIR = str(PROJECT_ROOT / "embeddings")
COLLECTION_NAME = "gold_scores"

_client: chromadb.ClientAPI | None = None
_client_lock = threading.Lock()


def get_client() -> chromadb.ClientAPI:
    """Return the shared ChromaDB client, creating lazily.

    Thread-safe: uses a lock to prevent concurrent initialisation. Subsequent
    calls after the first are lock-free (double-checked pattern).

    Uses HttpClient when CHROMADB_HOST is set (Docker / remote),
    otherwise PersistentClient writing to the local embeddings/ directory.
    """
    global _client
    if _client is not None:
        return _client

    with _client_lock:
        # Re-check inside the lock in case another thread initialised while we waited
        if _client is not None:
            return _client

        host = os.environ.get("CHROMADB_HOST", "")
        try:
            port = int(os.environ.get("CHROMADB_PORT", "8001"))
        except ValueError:
            logger.warning("Invalid CHROMADB_PORT, defaulting to 8001")
            port = 8001

        if host:
            _client = chromadb.HttpClient(host=host, port=port)
            logger.info("ChromaDB: connected to http://%s:%d", host, port)
        else:
            _client = chromadb.PersistentClient(path=_PERSIST_DIR)
            logger.info("ChromaDB: using PersistentClient at %s", _PERSIST_DIR)

    return _client


def get_collection() -> chromadb.Collection:
    """Return the gold_scores collection, creating if it does not exist."""
    client = get_client()
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"description": "Gold-layer borough health scores for RAG retrieval"},
    )


def close_client() -> None:
    """Reset the cached client. Call on process shutdown."""
    global _client
    _client = None
