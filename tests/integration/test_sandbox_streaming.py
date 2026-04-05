import time

from fastapi.testclient import TestClient

from backend.app.core.state import shared_state
from backend.app.main import app


def _configure_stream_test(tmp_path, monkeypatch) -> None:
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


def test_sandbox_live_stream_by_run_id(tmp_path, monkeypatch) -> None:
    _configure_stream_test(tmp_path, monkeypatch)
    with shared_state.lock:
        shared_state.sandbox_runs.clear()

    client = TestClient(app)
    create = client.post(
        "/sandbox/runs",
        json={
            "episode_spec": {
                "name": "stream-demo",
                "horizon": 20,
                "nodes": [
                    {"id": "host-01", "severity": "high"},
                    {"id": "host-02", "severity": "medium"},
                ],
                "vulnerabilities": [{"node_id": "host-01", "vuln_id": "SYNTH-CVE-2026-1001"}],
                "red_objectives": [{"target_node_id": "host-01", "objective": "exfiltrate"}],
                "defender_mode": "aegis",
            }
        },
    )
    assert create.status_code == 200
    run_id = create.json()["run_id"]

    saw_action = False
    saw_marker = False
    with client.websocket_connect(f"/stream/live/{run_id}") as ws:
        for _ in range(600):
            message = ws.receive_json()
            event_type = message.get("event_type") or message.get("type")
            if event_type == "action":
                saw_action = True
            if event_type == "marker":
                saw_marker = True
                break
            time.sleep(0.001)

    assert saw_action
    assert saw_marker

