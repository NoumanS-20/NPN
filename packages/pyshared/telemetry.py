"""Request timing and error counts, held in memory.

Two of the judging criteria are "real-time decisions" and "process of
monitoring", and both are easier to claim than to show. This module is how we
show them: every request is timed, the numbers are served from an endpoint, and
the panel can watch them move while they click.

Deliberately small. No Prometheus, no external collector, no persistence — a
ring buffer per endpoint and a lock. A hackathon prototype that shipped a
monitoring stack it could not explain would be worse than one that ships a
hundred lines it can.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from threading import Lock

# Enough history to make a percentile meaningful, small enough to stay free.
_WINDOW = 200


@dataclass
class EndpointStats:
    durations: deque[float] = field(default_factory=lambda: deque(maxlen=_WINDOW))
    requests: int = 0
    errors: int = 0
    last_status: int = 0


class Telemetry:
    """Per-endpoint request counts, error counts and latency percentiles."""

    def __init__(self) -> None:
        self._stats: dict[str, EndpointStats] = defaultdict(EndpointStats)
        self._lock = Lock()
        self._started = time.time()

    def record(self, endpoint: str, seconds: float, status: int) -> None:
        with self._lock:
            stats = self._stats[endpoint]
            stats.durations.append(seconds * 1000)
            stats.requests += 1
            stats.last_status = status
            if status >= 500:
                stats.errors += 1

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            endpoints = []
            total_requests = total_errors = 0

            for endpoint, stats in sorted(self._stats.items()):
                ordered = sorted(stats.durations)
                total_requests += stats.requests
                total_errors += stats.errors
                endpoints.append({
                    "endpoint": endpoint,
                    "requests": stats.requests,
                    "errors": stats.errors,
                    "last_status": stats.last_status,
                    "p50_ms": round(_percentile(ordered, 0.50), 1),
                    "p95_ms": round(_percentile(ordered, 0.95), 1),
                    "max_ms": round(ordered[-1], 1) if ordered else 0.0,
                })

            return {
                "uptime_seconds": round(time.time() - self._started, 1),
                "requests": total_requests,
                "errors": total_errors,
                "error_rate": round(total_errors / total_requests, 4) if total_requests else 0.0,
                "endpoints": endpoints,
            }

    def reset(self) -> None:
        with self._lock:
            self._stats.clear()
            self._started = time.time()


def _percentile(ordered: list[float], fraction: float) -> float:
    if not ordered:
        return 0.0
    index = min(int(len(ordered) * fraction), len(ordered) - 1)
    return ordered[index]


telemetry = Telemetry()


def install(app, skip_prefixes: tuple[str, ...] = ("/shared", "/js", "/css", "/pages")) -> None:
    """Add the timing middleware to a FastAPI application.

    Static files are skipped: they would swamp the numbers and tell nobody
    anything about how fast a plan solves.
    """

    @app.middleware("http")
    async def measure(request, call_next):
        path = request.url.path
        if path.startswith(skip_prefixes) or path == "/":
            return await call_next(request)

        started = time.perf_counter()
        response = await call_next(request)
        telemetry.record(path, time.perf_counter() - started, response.status_code)
        response.headers["X-Response-Time-Ms"] = f"{(time.perf_counter() - started) * 1000:.1f}"
        return response
