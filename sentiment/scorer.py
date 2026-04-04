"""
Local sentiment scorer.

Loads cardiffnlp/twitter-roberta-base-sentiment and scores text (Reddit post
titles/bodies, Guardian trailText) locally on CPU. Returns a float in [-1, 1]
which is normalised to 0–100 for the Silver layer.
Raw text is never written to disk or sent to any external API.
"""
