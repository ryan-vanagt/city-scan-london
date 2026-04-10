"""
ChromaDB client for agent tools (read side).

Provides access to the gold_scores collection for semantic similarity
search by the Doctor Agent's RAG retrieval. Same client pattern as
pipeline/chroma_client.py but resolved from the agents/tools/ path.
"""

import logging
import os
import threading
from pathlib import Path

import chromadb

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_PERSIST_DIR = str(PROJECT_ROOT / "embeddings")
COLLECTION_NAME = "gold_scores"

_client: chromadb.ClientAPI | None = None
_lock = threading.Lock()


def get_client() -> chromadb.ClientAPI:
    """Return the shared ChromaDB client, creating lazily.

    Uses HttpClient when CHROMADB_HOST is set (Docker / remote),
    otherwise PersistentClient reading from the local embeddings/ directory.
    """
    global _client
    if _client is not None:
        return _client

    with _lock:
        if _client is None:  # double-check after acquiring lock
            host = os.environ.get("CHROMADB_HOST", "")
            port = int(os.environ.get("CHROMADB_PORT", "8001"))

            if host:
                _client = chromadb.HttpClient(host=host, port=port)
                logger.info("Agent ChromaDB: connected to http://%s:%d", host, port)
            else:
                _client = chromadb.PersistentClient(path=_PERSIST_DIR)
                logger.info("Agent ChromaDB: using PersistentClient at %s", _PERSIST_DIR)

    return _client


def get_collection() -> chromadb.Collection:
    """Return the gold_scores collection (must already exist from pipeline embed step).

    Raises a clear error if the collection does not exist, indicating the
    embedding pipeline needs to be run first.
    """
    client = get_client()
    try:
        return client.get_collection(name=COLLECTION_NAME)
    except Exception as exc:
        logger.error("ChromaDB collection '%s' not found: %s", COLLECTION_NAME, exc)
        raise ValueError(
            "ChromaDB collection not found — run the embedding pipeline first"
        ) from exc


def close_client() -> None:
    """Reset the cached client. Call on process shutdown."""
    global _client
    with _lock:
        _client = None
