"""
One-shot manual pipeline trigger for development use.

Runs a single full cycle: fetch all sources → Bronze → Silver → Gold → embed.
Not used in production (scheduler.py handles that).
"""
