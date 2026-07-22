"""Observability layer for the M10 backend.

This module is where you (the learner) declare the three Prometheus metric
families and implement the three ASGI middleware classes that the autograder
exercises through the FastAPI app.

What lives here, and why:

  - Three metric families. A counter for request volume by (path, status), a
    histogram for request latency by path, and a gauge for in-flight requests.
    Together they answer "how much traffic, how slow, how concurrent."

  - Three middlewares. A request-id layer that attaches a per-request
    correlation id to the response and to the logging context. A
    structured-logging layer that emits one JSON line per response. A metrics
    layer that increments the counter, observes the latency histogram, and
    brackets the request with the in-flight gauge.

  Ordering matters: request-id is outermost (so it wraps the logging line),
  logging is middle, metrics is innermost (closest to the route).

Where to put what:

  - Declarations at MODULE SCOPE. If you declare a Counter / Histogram / Gauge
    inside a function or inside a middleware __call__, you will hit
    `Duplicated timeseries in CollectorRegistry` on the second request --
    every request re-runs the function. Module scope means the registry sees
    the declaration once at import time.

  - Label cardinality matters. The Lab's `requests_total` Counter uses
    exactly two labels: {path, status}. Do NOT add user-id, query-text,
    full-URL, or any other unbounded label.

Methodology pointers:

  - Reading sections 6-10 cover middleware, metric types, label cardinality.
  - See Common Pitfalls #1-#4 in the lab guide.
"""

"""Observability layer for the M10 backend."""



import json
import logging
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Callable, MutableMapping

from prometheus_client import Counter, Gauge, Histogram


request_id_var: ContextVar[str] = ContextVar("request_id", default="")


requests_total = Counter(
    "requests_total",
    "Total HTTP requests by path and status.",
    ["path", "status"],
)

request_latency_seconds = Histogram(
    "request_latency_seconds",
    "HTTP request latency in seconds by path.",
    ["path"],
)

inflight_requests = Gauge(
    "inflight_requests",
    "Number of HTTP requests currently in flight.",
)


_logger = logging.getLogger("m11.api")


def _path_label(scope: MutableMapping[str, Any]) -> str:
    """Return the parameterized route path when available, else raw path."""
    route = scope.get("route")
    if route is not None and hasattr(route, "path"):
        return route.path
    return scope.get("path", "")


class RequestIdMiddleware:
    """Generate a request id and attach it to the response."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid.uuid4().hex
        token = request_id_var.set(request_id)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("utf-8")))
                message["headers"] = headers

            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            request_id_var.reset(token)


class StructuredLoggingMiddleware:
    """Emit one structured JSON log line per HTTP request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status = 500

        async def send_wrapper(message):
            nonlocal status

            if message["type"] == "http.response.start":
                status = message["status"]

            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            latency_ms = (time.perf_counter() - start) * 1000

            log_line = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "level": "INFO",
                "request_id": request_id_var.get(),
                "path": _path_label(scope),
                "status": status,
                "latency_ms": round(latency_ms, 3),
            }

            _logger.info(json.dumps(log_line))


class MetricsMiddleware:
    """Record Prometheus metrics for each HTTP request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        inflight_requests.inc()
        start = time.perf_counter()
        status = 500

        async def send_wrapper(message):
            nonlocal status

            if message["type"] == "http.response.start":
                status = message["status"]

            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed = time.perf_counter() - start
            path = _path_label(scope)

            requests_total.labels(path=path, status=str(status)).inc()
            request_latency_seconds.labels(path=path).observe(elapsed)
            inflight_requests.dec()