"""Replication pipeline: seed plans, incremental sync, state, and checks.

Loads execute only from a confirmed plan (the SEED gate), and watermarks
advance only after publication, load, and validation succeed (INC-005).
"""
