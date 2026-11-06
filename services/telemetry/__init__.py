"""Dr. Flash — Structured Telemetry.

Structured JSON logging with no secrets, correlation IDs,
and performance tracking. Local-only by default.
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timezone

import structlog


_LEVEL_MAP = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


def setup_logging(level: str = "INFO") -> None:
    """Configure structured logging for the application."""
    numeric_level = _LEVEL_MAP.get(level.upper(), 20)
    logging.basicConfig(format="%(message)s", level=numeric_level, stream=sys.stderr)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer() if sys.stderr.isatty() else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


class MetricsCollector:
    """Simple in-memory metrics for cost, latency, and request tracking."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = {}

    def increment(self, name: str, value: int = 1) -> None:
        self._counters[name] = self._counters.get(name, 0) + value

    def gauge(self, name: str, value: float) -> None:
        self._gauges[name] = value

    def observe(self, name: str, value: float) -> None:
        if name not in self._histograms:
            self._histograms[name] = []
        self._histograms[name].append(value)

    def summary(self) -> dict:
        result: dict = {
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "histograms": {},
        }
        for name, values in self._histograms.items():
            if values:
                sorted_vals = sorted(values)
                n = len(sorted_vals)
                result["histograms"][name] = {
                    "count": n,
                    "mean": sum(sorted_vals) / n,
                    "p50": sorted_vals[n // 2],
                    "p95": sorted_vals[int(n * 0.95)] if n >= 20 else sorted_vals[-1],
                    "min": sorted_vals[0],
                    "max": sorted_vals[-1],
                }
        return result


metrics = MetricsCollector()
