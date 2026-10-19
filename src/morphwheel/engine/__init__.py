"""Conversion engines: job dispatcher (GUI side), worker pool, worker entry point, file ops.

Workers never import Qt (phase-4 §1, R2) and are the only processes that run plugin code.
"""
