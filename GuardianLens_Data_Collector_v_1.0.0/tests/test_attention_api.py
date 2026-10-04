from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from guardianlens.capture import create_capture
from guardianlens.db import transaction
from guardianlens.models import CaptureRequest
from guardianlens.security import ensure_local_token
from conftest import data_url, image_bytes


@pytest.fixture()
def attention_api(isolated, monkeypatch):
    module = importlib.import_module("guardianlens.app")
    status = {
        "run": {"run_id": "run-1", "status": "completed", "mode": "inspect"},
        "progress": {"total": 125, "inspected": 125, "awaiting_capture": 2},
        "items": [],
    }
    manager = SimpleNamespace(
        start=Mock(return_value=status),
        status=Mock(return_value=status),
        command=Mock(return_value=status),
        record_history=Mock(return_value=[]),
        recoverable_listing_ids=Mock(return_value=["listing-1", "listing-2"]),
    )
    monkeypatch.setattr(module, "attention_agent_manager", manager)
    return TestClient(module.app), manager, module


def auth():
    return {"X-GuardianLens-Token": ensure_local_token()}


@pytest.mark.parametrize(
    "path,payload",
    [
        ("/api/attention/start", {"mode": "repair"}),
        ("/api/attention/run-1/command/pause", {}),
        ("/api/attention/run-1/recover-sellers", {}),
    ],
)
def test_attention_mutations_require_token(attention_api, path, payload):
    client, manager, _ = attention_api
    assert client.post(path, json=payload).status_code == 401
    manager.start.assert_not_called()
    manager.command.assert_not_called()
    manager.recoverable_listing_ids.assert_not_called()


def test_attention_start_preserves_exact_scope_and_limits(attention_api):
    client, manager, _ = attention_api
    payload = {
        "mode": "repair",
        "listing_ids": ["listing-2", "listing-1"],
        "platform": "mudah",
        "reason": "missing_field",
        "item_limit": 25,
        "time_limit_minutes": 10,
        "api_call_limit": 0,
        "watch": True,
    }
    response = client.post("/api/attention/start", json=payload, headers=auth())
    assert response.status_code == 200
    manager.start.assert_called_once_with(**payload, recovery_batch_id=None)


@pytest.mark.parametrize(
    "payload",
    [
        {"mode": "approve"},
        {"platform": "unsupported"},
        {"listing_ids": []},
        {"listing_ids": [" "]},
        {"listing_ids": ["a" * 65]},
        {"listing_ids": ["listing"] * 10001},
        {"item_limit": 0},
        {"item_limit": True},
        {"item_limit": 10001},
        {"time_limit_minutes": 0},
        {"time_limit_minutes": 721},
        {"api_call_limit": -1},
        {"api_call_limit": 0.5},
        {"recovery_batch_id": ""},
        {"unexpected_option": "ignored"},
    ],
)
def test_attention_rejects_invalid_input_before_start(attention_api, payload):
    client, manager, _ = attention_api
    response = client.post("/api/attention/start", json=payload, headers=auth())
    assert response.status_code == 422
    manager.start.assert_not_called()


def test_attention_conflicts_and_missing_runs_have_clear_errors(attention_api):
    client, manager, _ = attention_api
    manager.start.side_effect = RuntimeError("finish the current processing run")
    response = client.post("/api/attention/start", json={}, headers=auth())
    assert response.status_code == 409
    assert "current processing run" in response.json()["detail"]
    manager.command.side_effect = KeyError("missing")
    assert client.post("/api/attention/missing/command/pause", headers=auth()).status_code == 404
    manager.command.reset_mock()
    assert client.post("/api/attention/run-1/command/approve", headers=auth()).status_code == 404
    manager.command.assert_not_called()
    manager.status.side_effect = KeyError("missing")
    assert client.get("/api/attention/status?run_id=missing").status_code == 404


def test_attention_read_api_and_dashboard_are_available(attention_api):
    client, manager, _ = attention_api
    response = client.get("/api/attention/status?run_id=run-1")
    assert response.status_code == 200
    assert response.json()["progress"]["inspected"] == 125
    manager.status.assert_called_with("run-1")
    assert client.get("/api/attention/records/listing-1").json() == []
    manager.record_history.assert_called_with("listing-1")
    dashboard = client.get("/")
    assert dashboard.status_code == 200
    for text in (
        "Needs attention agent", "Inspect all", "Start repair", "Watch for new",
        "Choose exact records", "/static/attention_agent.js",
        "Process recovered seller evidence",
    ):
        assert text in dashboard.text
    assert 'id="attentionCount-inspected">125' in dashboard.text


def test_attention_seller_recovery_uses_only_run_selection(attention_api, monkeypatch):
    client, manager, module = attention_api
    result = {"batch": {"retry_batch_id": "retry-1", "status": "running"}}
    prepare = Mock(return_value={"batch": {"retry_batch_id": "retry-1"}})
    start = Mock(return_value=result)
    monkeypatch.setattr(module.seller_retry_manager, "prepare", prepare)
    monkeypatch.setattr(module.seller_retry_manager, "start", start)
    response = client.post("/api/attention/run-1/recover-sellers", headers=auth())
    assert response.status_code == 200
    assert response.json() == result
    manager.recoverable_listing_ids.assert_called_once_with("run-1")
    prepare.assert_called_once_with(
        name="Attention agent seller recovery", listing_ids=["listing-1", "listing-2"]
    )
    start.assert_called_once_with("retry-1")


def test_attention_seller_recovery_empty_scope_does_not_prepare(attention_api, monkeypatch):
    client, manager, module = attention_api
    manager.recoverable_listing_ids.return_value = []
    prepare = Mock()
    monkeypatch.setattr(module.seller_retry_manager, "prepare", prepare)
    assert client.post("/api/attention/run-1/recover-sellers", headers=auth()).status_code == 400
    prepare.assert_not_called()


def test_attention_can_process_exact_recovery_batch(attention_api):
    client, manager, _ = attention_api
    response = client.post(
        "/api/attention/start",
        json={"mode": "repair", "recovery_batch_id": "retry-1", "item_limit": 25},
        headers=auth(),
    )
    assert response.status_code == 200
    assert manager.start.call_args.kwargs["recovery_batch_id"] == "retry-1"
    assert manager.start.call_args.kwargs["listing_ids"] is None


def test_attention_history_renders_evidence_and_escapes_capture_content(attention_api):
    client, manager, _ = attention_api
    captured = create_capture(CaptureRequest(
        platform="mudah",
        source_url="https://www.mudah.my/test-listing-123456.htm",
        page_title="Synthetic listing",
        screenshot_data_url=data_url(image_bytes()),
        image_urls=["https://images.example.test/product.jpg"],
        listing_evidence={"h1_text": "Synthetic listing", "has_price_signal": True},
    ))
    listing_id = captured["listing_id"]
    with transaction() as con:
        con.execute("UPDATE listings SET status='needs_attention' WHERE listing_id=?", (listing_id,))
    manager.record_history.return_value = [{
        "run_id": "run-1", "run_mode": "repair", "outcome": "awaiting_human",
        "finished_at": "2026-09-07", "findings": [{
            "code": "missing_field", "field": "seller_rating",
            "message": "Seller rating is missing", "action": "capture_seller",
        }],
        "changes": [{
            "field": "title", "before": None, "after": "<script>unsafe()</script>",
            "evidence": {"source": "listing_text", "reference": "capture-1"},
            "provider": "test", "model": "synthetic", "prompt_version": "v1",
        }],
    }]
    for path in (f"/records/{listing_id}", f"/review/{listing_id}"):
        response = client.get(path)
        assert response.status_code == 200
        assert "Agent inspection and changes" in response.text
        assert "Seller rating is missing" in response.text
        assert "capture seller" in response.text
        assert "listing_text" in response.text
        assert "Not extracted" in response.text
        assert "&lt;script&gt;unsafe()&lt;/script&gt;" in response.text
        assert "<script>unsafe()</script>" not in response.text
