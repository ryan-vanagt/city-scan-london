"""
APScheduler entry point for the ingestion service.

Runs all data source collectors on their respective schedules, then triggers
the full Bronze → Silver → Gold pipeline chain after each fetch cycle.
"""
