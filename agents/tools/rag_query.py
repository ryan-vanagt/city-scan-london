"""
RAG retrieval tool — semantic search over ChromaDB gold_scores embeddings.

Used by the Doctor Agent to find relevant borough health context before
answering a natural language query. Returns the top-k most semantically
similar borough score descriptions.
"""

import logging

logger = logging.getLogger(__name__)


def search_scores(
    query: str,
    n_results: int = 5,
    borough_code: str | None = None,
) -> dict:
    """Search ChromaDB for borough health scores relevant to a query.

    Args:
        query: Natural language query text (e.g. 'worst air quality').
        n_results: Maximum number of results to return (default 5).
        borough_code: Optional ONS code filter to scope results to one borough.

    Returns:
        Dict with 'results' (list of dicts with document, metadata,
        distance) and 'count'. Returns empty results with 'error' on failure.
    """
    try:
        from agents.tools.chroma_client import get_collection

        collection = get_collection()

        where_filter = {"borough_code": borough_code} if borough_code else None

        results = collection.query(
            query_texts=[query],
            n_results=min(n_results, 20),
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )

        items = []
        if results["documents"] and results["documents"][0]:
            for i, doc in enumerate(results["documents"][0]):
                items.append({
                    "document": doc,
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i],
                })

        return {"results": items, "count": len(items)}

    except Exception as exc:
        logger.warning("RAG search failed: %s", exc)
        return {"results": [], "count": 0, "error": str(exc)}
