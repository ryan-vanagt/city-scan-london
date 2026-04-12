"""Test sentiment/scorer.py — model loading, scoring, edge cases."""

import pytest

from sentiment.scorer import score_texts

pytestmark = pytest.mark.slow


def test_empty_input_returns_empty_list():
    result = score_texts([])
    assert result == []


def test_positive_text_scores_above_zero():
    positive = score_texts(["I love London, it's a beautiful city!"])
    assert len(positive) == 1
    assert positive[0] > 0, f"got {positive}"


def test_negative_text_scores_below_zero():
    negative = score_texts(["Terrible crime wave, everything is awful"])
    assert len(negative) == 1
    assert negative[0] < 0, f"got {negative}"


def test_neutral_text_returns_score():
    neutral = score_texts(["The meeting is at 3pm tomorrow"])
    assert len(neutral) == 1


def test_batch_returns_correct_count():
    batch = score_texts(["Good news", "Bad news", "Just news", "Amazing day", "Horrible weather"])
    assert len(batch) == 5, f"expected 5 scores, got {len(batch)}"


def test_all_scores_in_valid_range():
    positive = score_texts(["I love London, it's a beautiful city!"])
    negative = score_texts(["Terrible crime wave, everything is awful"])
    neutral  = score_texts(["The meeting is at 3pm tomorrow"])
    batch    = score_texts(["Good news", "Bad news", "Just news", "Amazing day", "Horrible weather"])

    all_scores = positive + negative + neutral + batch
    out_of_range = [s for s in all_scores if not (-1 <= s <= 1)]
    assert len(out_of_range) == 0, f"scores out of [-1, 1]: {out_of_range}"


def test_positive_score_greater_than_negative():
    positive = score_texts(["I love London, it's a beautiful city!"])
    negative = score_texts(["Terrible crime wave, everything is awful"])
    assert positive[0] > negative[0], \
        f"positive={positive[0]:.3f} not > negative={negative[0]:.3f}"
