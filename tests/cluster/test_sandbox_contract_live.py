from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest

try:
    import websockets
except ModuleNotFoundError:  # pragma: no cover - runtime guard
    websockets = None  # type: ignore[assignment]


pytestmark = [
    pytest.mark.skipif(
        os.getenv("RUN_CLUSTER_TESTS") != "1",
        reason="Set RUN_CLUSTER_TESTS=1 to run live cluster contract tests.",
    ),
    pytest.mark.skipif(websockets is None, reason="websockets package is required."),
]


TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
BASE_HTTP_URL = os.getenv("BASE_HTTP_URL", "http://127.0.0.1:8000").rstrip("/")
BASE_WS_URL = os.getenv("BASE_WS_URL", "ws://127.0.0.1:8000").rstrip("/")
HTTP_TIMEOUT_S = float(os.getenv("CLUSTER_HTTP_TIMEOUT_S", "30"))
TERMINAL_TIMEOUT_S = float(os.getenv("CLUSTER_TERMINAL_TIMEOUT_S", "180"))
WS_TIMEOUT_S = float(os.getenv("CLUSTER_WS_TIMEOUT_S", "120"))


def _default_evidence_dir() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return Path("artifacts/cluster_validation") / timestamp / "pass_local"


EVIDENCE_DIR = Path(os.getenv("CLUSTER_VALIDATION_EVIDENCE_DIR", str(_default_evidence_dir())))


RETRYABLE_HTTP_ERRORS = (
    httpx.ConnectError,
    httpx.ReadError,
    httpx.RemoteProtocolError,
    httpx.TimeoutException,
    httpx.WriteError,
)


def _event_type(message: dict[str, Any]) -> str | None:
    return message.get("event_type") or message.get("type")


def _write_json(relative_path: str, payload: Any) -> None:
    target = EVIDENCE_DIR / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _build_episode_spec(
    *,
    name: str,
    horizon: int,
    vuln_id: str,
    objective: str,
    seed: int = 1337,
) -> dict[str, Any]:
    return {
        "name": name,
        "seed": seed,
        "horizon": horizon,
        "nodes": [
            {"id": "host-01", "severity": "high", "role": "db"},
            {"id": "host-02", "severity": "medium", "role": "api"},
        ],
        "vulnerabilities": [{"node_id": "host-01", "vuln_id": vuln_id, "exploitability": 0.9}],
        "red_objectives": [{"target_node_id": "host-01", "objective": objective, "priority": 10}],
        "defender_mode": "aegis",
    }


def _request_with_retries(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    attempts: int = 6,
    sleep_s: float = 1.0,
    **kwargs: Any,
) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return client.request(method, path, **kwargs)
        except RETRYABLE_HTTP_ERRORS as exc:
            last_error = exc
            if attempt == attempts:
                break
            time.sleep(sleep_s)
    raise AssertionError(
        f"request failed after {attempts} attempts: {method} {path}"
    ) from last_error


def _wait_for_backend_ready(client: httpx.Client, *, timeout_s: float = 90.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            response = _request_with_retries(
                client,
                "GET",
                "/sandbox/catalog",
                attempts=1,
                sleep_s=0.2,
            )
        except AssertionError:
            time.sleep(1.0)
            continue
        if response.status_code == 200:
            return
        time.sleep(1.0)
    raise AssertionError("backend did not become ready for /sandbox/catalog within timeout")


def _wait_for_terminal(
    client: httpx.Client,
    run_id: str,
    *,
    timeout_s: float = TERMINAL_TIMEOUT_S,
    poll_interval_s: float = 0.5,
) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
    deadline = time.time() + timeout_s
    status_history: list[str] = []
    snapshots: list[dict[str, Any]] = []
    last_payload: dict[str, Any] = {}
    while time.time() < deadline:
        response = _request_with_retries(client, "GET", f"/sandbox/runs/{run_id}")
        assert response.status_code == 200, response.text
        last_payload = response.json()
        status_value = str(last_payload["status"])
        status_history.append(status_value)
        snapshots.append(last_payload)
        if status_value in TERMINAL_STATUSES:
            return last_payload, status_history, snapshots
        time.sleep(poll_interval_s)
    raise AssertionError(f"run {run_id} did not reach terminal state in {timeout_s} seconds")


async def _collect_ws_with_forced_reconnect(
    run_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    first_connection: list[dict[str, Any]] = []
    second_connection: list[dict[str, Any]] = []
    uri = f"{BASE_WS_URL}/stream/live/{run_id}"

    first_deadline = time.monotonic() + min(30.0, WS_TIMEOUT_S)
    async with websockets.connect(uri, open_timeout=10, close_timeout=5, ping_interval=None) as ws:
        while time.monotonic() < first_deadline:
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            message = json.loads(raw)
            first_connection.append(message)
            event_type = _event_type(message)
            # Force a disconnect after at least one non-terminal event.
            if event_type in {"action", "metric"} and len(first_connection) >= 2:
                await ws.close()
                break
            if event_type == "marker":
                break

    # Reconnect to validate fallback behavior.
    second_deadline = time.monotonic() + WS_TIMEOUT_S
    async with websockets.connect(uri, open_timeout=10, close_timeout=5, ping_interval=None) as ws:
        while time.monotonic() < second_deadline:
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            message = json.loads(raw)
            second_connection.append(message)
            if _event_type(message) == "marker":
                break

    return first_connection, second_connection


def _assert_terminal_summary_ready(payload: dict[str, Any]) -> None:
    status = payload.get("status")
    assert status in TERMINAL_STATUSES, f"unexpected terminal status: {status}"
    assert isinstance(payload.get("artifact_paths"), dict), "artifact_paths missing"
    if status == "completed":
        assert isinstance(payload.get("kpis"), dict), "kpis must be present for completed runs"
    if status == "failed":
        assert payload.get("error"), "error must be present for failed runs"


def _assert_rate_or_concurrency_limit(
    client: httpx.Client,
    *,
    vuln_id: str,
    objective: str,
) -> tuple[bool, list[str], list[dict[str, Any]]]:
    trigger_headers = {"x-forwarded-for": "cluster-contract-limit-probe"}
    created_run_ids: list[str] = []
    attempts: list[dict[str, Any]] = []
    limited = False
    try:
        for idx in range(1, 8):
            payload = {
                "episode_spec": _build_episode_spec(
                    name=f"limit-probe-{idx}",
                    horizon=300,
                    vuln_id=vuln_id,
                    objective=objective,
                    seed=1700 + idx,
                )
            }
            response = _request_with_retries(
                client,
                "POST",
                "/sandbox/runs",
                json=payload,
                headers=trigger_headers,
            )
            attempts.append(
                {
                    "attempt": idx,
                    "status_code": response.status_code,
                    "body": (
                        response.json()
                        if response.headers.get("content-type", "").startswith("application/json")
                        else response.text
                    ),
                }
            )
            if response.status_code == 429:
                limited = True
                break
            assert response.status_code == 200, response.text
            created_run_ids.append(response.json()["run_id"])
            time.sleep(0.1)
    finally:
        for run_id in created_run_ids:
            _request_with_retries(client, "POST", f"/sandbox/runs/{run_id}/cancel")
    return limited, created_run_ids, attempts


def test_partner_handoff_live_cluster_contract() -> None:
    evidence_summary: dict[str, Any] = {
        "base_http_url": BASE_HTTP_URL,
        "base_ws_url": BASE_WS_URL,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "doc_checks": {},
    }
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    submitting_state_seen = False
    created_run_ids: list[str] = []

    with httpx.Client(base_url=BASE_HTTP_URL, timeout=HTTP_TIMEOUT_S) as client:
        _wait_for_backend_ready(client)

        health = _request_with_retries(client, "GET", "/health")
        health_ok = False
        if health.status_code == 200:
            health_payload = health.json()
            health_ok = health_payload.get("status") == "ok"
            _write_json("health.json", health_payload)
        else:
            _write_json(
                "health.json",
                {"status_code": health.status_code, "body": health.text[:1000]},
            )

        catalog = _request_with_retries(client, "GET", "/sandbox/catalog")
        assert catalog.status_code == 200, catalog.text
        catalog_payload = catalog.json()
        vulnerabilities = catalog_payload.get("vulnerabilities")
        objectives = catalog_payload.get("objectives")
        assert (
            isinstance(vulnerabilities, list) and vulnerabilities
        ), "catalog vulnerabilities is empty"
        assert isinstance(objectives, list) and objectives, "catalog objectives is empty"
        vuln_id = str(vulnerabilities[0])
        objective = "exfiltrate" if "exfiltrate" in objectives else str(objectives[0])
        _write_json("catalog.json", catalog_payload)

        # Happy path run with reconnect + polling reconciliation.
        happy_payload = {
            "episode_spec": _build_episode_spec(
                name=f"contract-happy-{uuid4().hex[:8]}",
                horizon=180,
                vuln_id=vuln_id,
                objective=objective,
            )
        }
        submitting_state_seen = True
        create = _request_with_retries(
            client,
            "POST",
            "/sandbox/runs",
            json=happy_payload,
            headers={"x-forwarded-for": "cluster-contract-happy"},
        )
        assert create.status_code == 200, create.text
        create_payload = create.json()
        run_id = create_payload["run_id"]
        created_run_ids.append(run_id)
        assert create_payload["status"] == "queued"
        assert create_payload["stream_url"] == f"/stream/live/{run_id}"
        _write_json("happy_create.json", create_payload)

        first_ws, second_ws = asyncio.run(_collect_ws_with_forced_reconnect(run_id))
        ws_combined = first_ws + second_ws
        _write_json(
            "websocket_transcript.json",
            {"first_connection": first_ws, "second_connection": second_ws},
        )
        assert ws_combined, "websocket stream did not return any events"
        for message in ws_combined:
            assert "payload" in message
            assert "run_id" in message
            assert message["run_id"] == run_id
            assert _event_type(message) in {"action", "metric", "marker"}
        assert any(_event_type(event) == "action" for event in ws_combined), "missing action event"
        assert any(_event_type(event) == "metric" for event in ws_combined), "missing metric event"
        marker_events = [event for event in ws_combined if _event_type(event) == "marker"]
        assert len(marker_events) == 1, (
            f"expected exactly one terminal marker, got {len(marker_events)}"
        )

        happy_terminal, happy_status_history, happy_poll_snapshots = _wait_for_terminal(
            client, run_id
        )
        _write_json("happy_poll_history.json", happy_status_history)
        _write_json("happy_poll_snapshots.json", happy_poll_snapshots[-20:])
        _write_json("happy_terminal.json", happy_terminal)
        assert happy_terminal["status"] == "completed"
        _assert_terminal_summary_ready(happy_terminal)

        # Cancel flow.
        cancel_payload = {
            "episode_spec": _build_episode_spec(
                name=f"contract-cancel-{uuid4().hex[:8]}",
                horizon=300,
                vuln_id=vuln_id,
                objective=objective,
                seed=1338,
            )
        }
        cancel_create = _request_with_retries(
            client,
            "POST",
            "/sandbox/runs",
            json=cancel_payload,
            headers={"x-forwarded-for": "cluster-contract-cancel"},
        )
        assert cancel_create.status_code == 200, cancel_create.text
        cancel_run_id = cancel_create.json()["run_id"]
        created_run_ids.append(cancel_run_id)
        cancel_response = _request_with_retries(
            client, "POST", f"/sandbox/runs/{cancel_run_id}/cancel"
        )
        assert cancel_response.status_code == 200, cancel_response.text
        _write_json("cancel_response.json", cancel_response.json())
        cancelled_terminal, cancelled_history, _ = _wait_for_terminal(client, cancel_run_id)
        _write_json("cancel_poll_history.json", cancelled_history)
        _write_json("cancel_terminal.json", cancelled_terminal)
        assert cancelled_terminal["status"] == "cancelled"
        _assert_terminal_summary_ready(cancelled_terminal)

        # Negative contract cases.
        invalid_horizon = _request_with_retries(
            client,
            "POST",
            "/sandbox/runs",
            json={
                "episode_spec": _build_episode_spec(
                    name=f"contract-invalid-horizon-{uuid4().hex[:8]}",
                    horizon=5,
                    vuln_id=vuln_id,
                    objective=objective,
                    seed=1339,
                )
            },
        )
        assert invalid_horizon.status_code == 400

        invalid_vuln = _request_with_retries(
            client,
            "POST",
            "/sandbox/runs",
            json={
                "episode_spec": _build_episode_spec(
                    name=f"contract-invalid-vuln-{uuid4().hex[:8]}",
                    horizon=120,
                    vuln_id="SYNTH-CVE-2099-9999",
                    objective=objective,
                    seed=1340,
                )
            },
        )
        assert invalid_vuln.status_code == 400

        unknown_status = _request_with_retries(client, "GET", "/sandbox/runs/run_does_not_exist")
        assert unknown_status.status_code == 404
        unknown_cancel = _request_with_retries(
            client, "POST", "/sandbox/runs/run_does_not_exist/cancel"
        )
        assert unknown_cancel.status_code == 404

        limited, limited_run_ids, limit_attempts = _assert_rate_or_concurrency_limit(
            client,
            vuln_id=vuln_id,
            objective=objective,
        )
        _write_json("limit_attempts.json", limit_attempts)
        _write_json("limit_created_run_ids.json", limited_run_ids)
        assert limited, "expected at least one 429 response under rate/concurrency pressure"

        # Synthetic failed summary readiness check for dashboard renderer behavior.
        failed_terminal_synthetic = dict(happy_terminal)
        failed_terminal_synthetic["status"] = "failed"
        failed_terminal_synthetic["error"] = "synthetic_failure_for_summary_readiness"
        failed_terminal_synthetic["kpis"] = None
        _assert_terminal_summary_ready(failed_terminal_synthetic)
        _write_json("failed_terminal_synthetic.json", failed_terminal_synthetic)

        evidence_summary["doc_checks"] = {
            "preflight": {
                "health_endpoint_ok": health_ok,
                "catalog_endpoint_reachable": True,
            },
            "doc01_product_flow": {
                "submitting_state_seen": submitting_state_seen,
                "queued_state_seen": create_payload["status"] == "queued",
                "running_seen_in_poll_history": "running" in happy_status_history,
                "terminal_completed_seen": happy_terminal["status"] == "completed",
                "cancelled_terminal_seen": cancelled_terminal["status"] == "cancelled",
                "reconnect_path_exercised": bool(first_ws and second_ws),
                "polling_authoritative_terminal": happy_terminal["status"] in TERMINAL_STATUSES,
            },
            "doc02_api_contract": {
                "catalog_shape_valid": bool(vulnerabilities and objectives),
                "create_response_fields_valid": (
                    "run_id" in create_payload
                    and "status" in create_payload
                    and "stream_url" in create_payload
                ),
                "status_endpoint_terminal_valid": happy_terminal["status"] in TERMINAL_STATUSES,
                "cancel_endpoint_terminal_valid": cancelled_terminal["status"] == "cancelled",
                "negative_400_horizon": invalid_horizon.status_code == 400,
                "negative_400_unknown_vuln": invalid_vuln.status_code == 400,
                "negative_404_unknown_run": unknown_status.status_code == 404,
                "negative_429_pressure": limited,
            },
            "doc03_live_stream_contract": {
                "envelope_fields_valid": all(
                    {"payload", "run_id"} <= set(message.keys())
                    and _event_type(message) is not None
                    for message in ws_combined
                ),
                "event_classes_seen": {
                    "action": any(_event_type(message) == "action" for message in ws_combined),
                    "metric": any(_event_type(message) == "metric" for message in ws_combined),
                    "marker": len(marker_events) == 1,
                },
                "exactly_one_terminal_marker": len(marker_events) == 1,
                "reconnect_plus_poll_reconciliation": (
                    happy_terminal["status"] == marker_events[0]["payload"]["status"]
                ),
            },
            "doc04_frontend_integration_checklist": {
                "synthetic_client_flow_executed": True,
                "ws_drop_fallback_exercised": bool(first_ws and second_ws),
                "terminal_from_polling_supported": happy_terminal["status"] in TERMINAL_STATUSES,
                "terminal_summary_ready_completed": True,
                "terminal_summary_ready_failed_synthetic": True,
                "terminal_summary_ready_cancelled": True,
            },
        }

    evidence_summary["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    evidence_summary["created_run_ids"] = created_run_ids
    _write_json("assertion_summary.json", evidence_summary)
