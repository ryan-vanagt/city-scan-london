"""
Reddit data source collector.

Fetches top 50 hot posts from r/london, r/londonuk, and r/ukpolitics (London-filtered)
using PRAW. Each post title + body is scored locally by the sentiment model before
anything is stored. Raw post text is never written to disk.
"""
