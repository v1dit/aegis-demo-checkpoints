import time
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.state import shared_state
from backend.app.main import app


def _configure_tmp_paths(tmp_path, monkeypatch) -> None:
    runs_dir = tmp_path / "runs"
    artifacts_dir = tmp_path / "artifacts"
    checkpoint_dir = artifacts_dir / "checkpoints"
    eval_dir = artifacts_dir / "eval_reports"
    replay_dir = artifacts_dir / "replays"
    active_run_file = runs_dir / ".active_run"

    monkeypatch.setattr("backend.app.core.paths.RUNS_DIR", runs_dir)
    monkeypatch.setattr("backend.app.core.paths.CHECKPOINT_DIR", checkpoint_dir)
    monkeypatch.setattr("backend.app.core.paths.EVAL_REPORT_DIR", eval_dir)
    monkeypatch.setattr("backend.app.core.paths.REPLAY_DIR", replay_dir)
    monkeypatch.setattr("backend.app.core.runs.RUNS_DIR", runs_dir)
    monkeypatch.setattr("backend.app.core.runs.CHECKPOINT_DIR", checkpoint_dir)
    monkeypatch.setattr("backend.app.core.runs.EVAL_REPORT_DIR", eval_dir)
    monkeypatch.setattr("backend.app.core.runs.REPLAY_DIR", replay_dir)
    monkeypatch.setattr("backend.app.core.runs.ACTIVE_RUN_FILE", active_run_file)
    monkeypatch.setattr("backend.app.api.stream.REPLAY_DIR", replay_dir)
    monkeypatch.setattr("backend.app.sandbox.jobs.settings.sandbox_step_delay_seconds", 0.005)


def _wait_terminal(client: TestClient, run_id: str, timeout_s: float = 10.0) -> dict:
    deadline = time.time() + timeout_s
    last_payload: dict = {}
    while time.time() < deadline:
        response = client.get(f"/sandbox/runs/{run_id}")
        assert response.status_code == 200
        last_payload = response.json()
        if last_payload["status"] in {"completed", "failed", "cancelled"}:
            return last_payload
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not reach terminal state")


def test_sandbox_run_create_and_complete(tmp_path, monkeypatch) -> None:
    _configure_tmp_paths(tmp_path, monkeypatch)
    with shared_state.lock:
        shared_state.sandbox_runs.clear()

    client = TestClient(app)
    create = client.post(
        "/sandbox/runs",
        json={
            "episode_spec": {
                "name": "demo",
                "horizon": 12,
                "nodes": [
                    {"id": "host-01", "severity": "high"},
                    {"id": "host-02", "severity": "medium"},
                ],
                "vulnerabilities": [
                    {"node_id": "host-01", "vuln_id": "SYNTH-CVE-2026-1001"},
                    {"node_id": "host-02", "vuln_id": "SYNTH-CVE-2026-1101"},
                ],
                "red_objectives": [
                    {"target_node_id": "host-02", "objective": "exfiltrate", "priority": 10}
                ],
                "defender_mode": "aegis",
            }
        },
    )
    assert create.status_code == 200
    payload = create.json()
    assert payload["status"] == "queued"
    run_id = payload["run_id"]

    terminal = _wait_terminal(client, run_id)
    assert terminal["status"] == "completed"
    assert isinstance(terminal.get("kpis"), dict)
    artifact_paths = terminal["artifact_paths"]
    assert Path(artifact_paths["episode_spec"]).exists()
    assert Path(artifact_paths["events"]).exists()
    assert Path(artifact_paths["summary"]).exists()


def test_sandbox_cancel_flow(tmp_path, monkeypatch) -> None:
    _configure_tmp_paths(tmp_path, monkeypatch)
    with shared_state.lock:
        shared_state.sandbox_runs.clear()

    client = TestClient(app)
    create = client.post(
        "/sandbox/runs",
        json={
            "episode_spec": {
                "name": "cancel-demo",
                "horizon": 200,
                "nodes": [{"id": "host-01", "severity": "high"}],
                "vulnerabilities": [{"node_id": "host-01", "vuln_id": "SYNTH-CVE-2026-1001"}],
                "red_objectives": [{"target_node_id": "host-01", "objective": "exfiltrate"}],
                "defender_mode": "aegis",
            }
        },
    )
    assert create.status_code == 200
    run_id = create.json()["run_id"]

    cancel = client.post(f"/sandbox/runs/{run_id}/cancel")
    assert cancel.status_code == 200

    terminal = _wait_terminal(client, run_id)
    assert terminal["status"] == "cancelled"


def test_sandbox_rejects_invalid_payload(tmp_path, monkeypatch) -> None:
    _configure_tmp_paths(tmp_path, monkeypatch)
    with shared_state.lock:
        shared_state.sandbox_runs.clear()

    client = TestClient(app)
    invalid = client.post(
        "/sandbox/runs",
        json={
            "episode_spec": {
                "name": "bad",
                "horizon": 5,
                "nodes": [{"id": "host-01", "severity": "high"}],
                "vulnerabilities": [],
                "red_objectives": [],
                "defender_mode": "aegis",
            }
        },
    )
    assert invalid.status_code == 400


def test_sandbox_catalog_endpoint(tmp_path, monkeypatch) -> None:
    _configure_tmp_paths(tmp_path, monkeypatch)
    with shared_state.lock:
        shared_state.sandbox_runs.clear()

    client = TestClient(app)
    response = client.get("/sandbox/catalog")
    assert response.status_code == 200
    payload = response.json()
    assert "vulnerabilities" in payload
    assert "objectives" in payload
    assert "exfiltrate" in payload["objectives"]
