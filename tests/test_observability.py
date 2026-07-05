"""YOUR tests for the observability layer."""

import json
import logging

from fastapi.testclient import TestClient

from api.main import app


client = TestClient(app)


def test_one():
    """RequestIdMiddleware adds an X-Request-ID response header."""
    response = client.get("/healthz")

    assert response.status_code == 200
    assert "x-request-id" in response.headers
    assert len(response.headers["x-request-id"]) >= 8


def test_two():
    """The /metrics endpoint exposes the custom Prometheus metrics."""
    client.get("/healthz")
    response = client.get("/metrics")

    assert response.status_code == 200

    body = response.text
    assert "requests_total" in body
    assert "request_latency_seconds" in body
    assert "inflight_requests" in body


def test_three(caplog):
    """StructuredLoggingMiddleware emits a parseable JSON log line."""
    with caplog.at_level(logging.INFO, logger="m11.api"):
        response = client.get("/healthz")

    assert response.status_code == 200

    matching_logs = []

    for record in caplog.records:
        try:
            payload = json.loads(record.getMessage())
        except json.JSONDecodeError:
            continue

        required_keys = {"request_id", "path", "status", "latency_ms"}
        if required_keys.issubset(payload):
            matching_logs.append(payload)

    assert matching_logs

    log = matching_logs[-1]
    assert log["path"] == "/healthz"
    assert log["status"] == 200
    assert len(log["request_id"]) >= 8
    assert isinstance(log["latency_ms"], float)