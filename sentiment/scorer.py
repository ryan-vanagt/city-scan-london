"""
Local sentiment scorer.

Loads cardiffnlp/twitter-roberta-base-sentiment and scores text (Reddit post
titles, BBC descriptions, Guardian trailText) locally on CPU. Returns floats
in [-1, 1] which the silver layer normalises to 0–100.
Raw text is never written to disk or sent to any external API.
"""

import logging

logger = logging.getLogger(__name__)

_MODEL_NAME = "cardiffnlp/twitter-roberta-base-sentiment"

# Lazy-loaded on first call to avoid startup cost
_pipeline = None


def _load_model():
    """Load the sentiment model lazily on first use."""
    global _pipeline
    if _pipeline is not None:
        return

    from transformers import pipeline as hf_pipeline  # noqa: C0415

    logger.info("Loading sentiment model: %s", _MODEL_NAME)
    _pipeline = hf_pipeline(
        "sentiment-analysis",
        model=_MODEL_NAME,
        tokenizer=_MODEL_NAME,
        top_k=3,  # return all 3 class probabilities
        truncation=True,
        max_length=512,
    )
    logger.info("Sentiment model loaded")


def score_texts(texts: list[str]) -> list[float]:
    """Score a batch of texts for sentiment.

    Uses cardiffnlp/twitter-roberta-base-sentiment which outputs three
    softmax probabilities: LABEL_0 (negative), LABEL_1 (neutral),
    LABEL_2 (positive). The score is computed as:
        score = prob_positive - prob_negative
    yielding a value in [-1, 1].

    Args:
        texts: List of text strings to score.

    Returns:
        List of floats in [-1, 1], one per input text.
        Empty list if input is empty.
    """
    if not texts:
        return []

    _load_model()

    results = _pipeline(texts)
    scores: list[float] = []

    for result in results:
        # result is a list of dicts: [{"label": "LABEL_0", "score": 0.8}, ...]
        probs = {item["label"]: item["score"] for item in result}
        prob_positive = probs.get("LABEL_2", 0.0)
        prob_negative = probs.get("LABEL_0", 0.0)
        scores.append(prob_positive - prob_negative)

    return scores
