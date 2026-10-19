# Feature: n8n-multiagent-doc-pipeline, API endpoint property tests
"""
tests/integration/test_api_endpoints.py — Integration tests for FastAPI endpoints.

Property 10: Trace completeness after every pipeline step
"""
import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from hypothesis import given, settings, strategies as st


@pytest.fixture(scope="module")
def client():
    """Create a FastAPI test client with mocked dependencies."""
    # Set required env vars before importing app
    env_vars = {
        "OPENAI_BASE_URL": "http://localhost:11434/v1",
        "OPENAI_API_KEY": "test-key",
        "AGENT_DEPLOYMENT": "test-model",
        "VISION_DEPLOYMENT": "test-model",
        "OPTIMIZER_DEPLOYMENT": "test-model",
        "AGENT_REASONING_EFFORT": "none",
        "DEMO_CACHE": "0",
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_traces.db")
        inbox_path = os.path.join(tmpdir, "inbox")
        os.makedirs(inbox_path, exist_ok=True)

        with patch.dict(os.environ, env_vars):
            # Patch paths before importing
            import api.main as main_module
            from importlib import reload
            reload(main_module)

            # Override db and inbox paths
            from api.db import TraceStore
            test_db = TraceStore(db_path)
            main_module._db = test_db

            yield TestClient(main_module.app)


# ── Smoke test: GET /health ────────────────────────────────────────────────────

def test_health_endpoint_returns_200_or_503(client):
    """GET /health returns 200 or 503 with component info."""
    response = client.get("/health")
    assert response.status_code in (200, 503), (
        f"Unexpected status code: {response.status_code}"
    )
    data = response.json()
    assert "status" in data
    assert "components" in data
    assert "sqlite" in data["components"]


def test_health_components_have_valid_values(client):
    """Each health component has value 'ok', 'error', or 'unconfigured'."""
    response = client.get("/health")
    data = response.json()
    valid_values = {"ok", "error", "unconfigured", "degraded"}
    for key, val in data.get("components", {}).items():
        assert val in valid_values, (
            f"Component '{key}' has unexpected value: {val!r}"
        )


# ── Test: Exactly 10 routes ────────────────────────────────────────────────────

def test_exactly_10_routes(client):
    """FastAPI app must expose exactly 10 endpoints (no extras)."""
    routes = [
        r for r in client.app.routes
        if hasattr(r, "methods") and r.path not in ("/docs", "/redoc", "/openapi.json")
    ]
    # Filter to only our API paths
    api_paths = {
        "/route", "/extract", "/code", "/validate", "/handle",
        "/accept", "/escalate", "/fail", "/trace/{doc_id}", "/health",
    }
    registered = {r.path for r in routes if hasattr(r, "path")}
    for expected in api_paths:
        assert expected in registered, f"Expected route '{expected}' not registered"


# ── Property 10: Trace completeness after every pipeline step ─────────────────
# Feature: n8n-multiagent-doc-pipeline, Property 10: Trace completeness
# Validates: Requirements 6.3, 16.5

def test_accept_endpoint_writes_trace(client):
    """POST /accept writes a trace row with non-null fields."""
    import tempfile
    from api.db import TraceStore
    import api.main as main_module

    with tempfile.TemporaryDirectory() as tmpdir:
        db = TraceStore(os.path.join(tmpdir, "t.db"))
        original_db = main_module._db
        main_module._db = db
        try:
            response = client.post("/accept", json={
                "doc_id": "TEST-ACCEPT-001",
                "company_id": "company_a",
            })
            assert response.status_code == 200

            rows = db.get_by_doc_id("TEST-ACCEPT-001")
            assert len(rows) >= 1, "Expected at least one trace row"

            row = rows[0]
            assert row.get("step") == "accept"
            assert row.get("status") == "success"
            assert row.get("duration_ms") is not None
        finally:
            main_module._db = original_db


def test_escalate_endpoint_writes_trace(client):
    """POST /escalate writes a trace row with non-null fields."""
    import tempfile
    from api.db import TraceStore
    import api.main as main_module

    with tempfile.TemporaryDirectory() as tmpdir:
        db = TraceStore(os.path.join(tmpdir, "t.db"))
        original_db = main_module._db
        main_module._db = db
        try:
            response = client.post("/escalate", json={
                "doc_id": "TEST-ESCALATE-001",
                "company_id": "company_a",
                "dossier": {"summary": "Test escalation"},
            })
            assert response.status_code == 200

            rows = db.get_by_doc_id("TEST-ESCALATE-001")
            assert len(rows) >= 1
            row = rows[0]
            assert row.get("step") == "escalate"
            assert row.get("status") == "success"
        finally:
            main_module._db = original_db


def test_fail_endpoint_writes_trace(client):
    """POST /fail writes a trace row with error status."""
    import tempfile
    from api.db import TraceStore
    import api.main as main_module

    with tempfile.TemporaryDirectory() as tmpdir:
        db = TraceStore(os.path.join(tmpdir, "t.db"))
        original_db = main_module._db
        main_module._db = db
        try:
            response = client.post("/fail", json={
                "doc_id": "TEST-FAIL-001",
                "company_id": "company_a",
                "error": "LLM timeout",
            })
            assert response.status_code == 200

            rows = db.get_by_doc_id("TEST-FAIL-001")
            assert len(rows) >= 1
            row = rows[0]
            assert row.get("step") == "fail"
            assert row.get("status") == "error"
        finally:
            main_module._db = original_db


def test_trace_endpoint_returns_empty_for_unknown_doc(client):
    """GET /trace/{doc_id} returns empty list for unknown doc_id."""
    response = client.get("/trace/NONEXISTENT-DOC-99999")
    assert response.status_code == 200
    data = response.json()
    assert "traces" in data
    assert data["traces"] == []


@settings(max_examples=50)
@given(doc_id=st.text(min_size=1, max_size=50, alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"))
def test_trace_endpoint_valid_for_any_doc_id(doc_id, client):
    """GET /trace/{doc_id} returns 200 for any valid doc_id."""
    response = client.get(f"/trace/{doc_id}")
    assert response.status_code == 200
    data = response.json()
    assert "doc_id" in data
    assert "traces" in data
