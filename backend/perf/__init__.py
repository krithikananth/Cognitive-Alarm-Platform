"""Performance benchmarking and load-testing harness for ICAP dashboards.

Modules:
    dataset         — deterministic synthetic data generator
    instrumentation — SQLAlchemy statement recorder + EXPLAIN helpers
    benchmark       — in-process API benchmark runner (CLI)
    loadtest/       — Locust and k6 scripts for HTTP-level load testing
"""
