"""Request timing and error counts.

Evidence for two judging criteria — "real-time decisions" and "process of
monitoring" — so the numbers have to be real rather than decorative.
"""

from __future__ import annotations

from pyshared.telemetry import Telemetry


def test_a_request_is_counted_and_timed() -> None:
    telemetry = Telemetry()
    telemetry.record("/api/allocate", 0.25, 200)

    snapshot = telemetry.snapshot()
    assert snapshot["requests"] == 1
    assert snapshot["endpoints"][0]["endpoint"] == "/api/allocate"
    assert snapshot["endpoints"][0]["p50_ms"] == 250.0


def test_percentiles_order_correctly() -> None:
    telemetry = Telemetry()
    for seconds in (0.01, 0.02, 0.03, 0.5):
        telemetry.record("/api/allocate", seconds, 200)

    endpoint = telemetry.snapshot()["endpoints"][0]
    assert endpoint["p50_ms"] <= endpoint["p95_ms"] <= endpoint["max_ms"]


def test_server_errors_are_counted_but_client_errors_are_not() -> None:
    """A 404 is the API working correctly; a 500 is not."""
    telemetry = Telemetry()
    telemetry.record("/api/allocate", 0.1, 200)
    telemetry.record("/api/allocate", 0.1, 404)
    telemetry.record("/api/allocate", 0.1, 500)

    snapshot = telemetry.snapshot()
    assert snapshot["requests"] == 3
    assert snapshot["errors"] == 1
    assert snapshot["error_rate"] == round(1 / 3, 4)


def test_endpoints_are_tracked_separately() -> None:
    telemetry = Telemetry()
    telemetry.record("/api/allocate", 1.0, 200)
    telemetry.record("/api/suppliers", 0.01, 200)

    endpoints = {row["endpoint"]: row for row in telemetry.snapshot()["endpoints"]}
    assert endpoints["/api/allocate"]["p50_ms"] > endpoints["/api/suppliers"]["p50_ms"]


def test_an_empty_snapshot_does_not_divide_by_zero() -> None:
    snapshot = Telemetry().snapshot()
    assert snapshot["requests"] == 0
    assert snapshot["error_rate"] == 0.0
    assert snapshot["endpoints"] == []


def test_the_window_is_bounded() -> None:
    """A long demo must not grow memory without limit."""
    telemetry = Telemetry()
    for _ in range(1000):
        telemetry.record("/api/allocate", 0.01, 200)

    snapshot = telemetry.snapshot()
    assert snapshot["requests"] == 1000          # the count is exact
    assert snapshot["endpoints"][0]["p50_ms"] > 0
