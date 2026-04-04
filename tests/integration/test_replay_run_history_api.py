from __future__ import annotations

import json

from fastapi.testclient import TestClient

from backend.app.main import app


def _write_replay_bundle(run_root, replay_id: str) -> None:
    replay_dir = run_root / "replays" / replay_id
    replay_dir.mkdir(parents=True, exist_ok=True)
    (replay_dir / "manifest.json").write_text(
        json.dumps(
            {
                "replay_id": replay_id,
                "scenario_id": "scenario_unseen_web_rce",
                "seed": 1001,
                "checkpoint_id": "ckpt_blue_main_001",
                "duration_steps": 5,
                "files": {
                    "events": "events.jsonl",
                    "topology": "topology_snapshots.json",
                    "metrics": "metrics.json",
                },
            }
        ),
        encoding="utf-8",
    )
    (replay_dir / "events.jsonl").write_text(
        '{"event_id":"evt_000001","ts_ms":1,"step":1,"actor":"RED","action_type":"scan_host"}\n',
        encoding="utf-8",
    )
    (replay_dir / "topology_snapshots.json").write_text("{}", encoding="utf-8")
    (replay_dir / "metrics.json").write_text("{}", encoding="utf-8")


def test_run_history_replay_endpoints(tmp_path, monkeypatch) -> None:
    runs_dir = tmp_path / "runs"
    active_run_file = runs_dir / ".active_run"
    run_001 = runs_dir / "run_001"
    run_002 = runs_dir / "run_002"
    run_001.mkdir(parents=True, exist_ok=True)
    run_002.mkdir(parents=True, exist_ok=True)

    (run_001 / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "run_001",
                "created_at": "2026-04-04T00:00:00+00:00",
                "updated_at": "2026-04-04T00:10:00+00:00",
                "train": {"status": "completed"},
                "eval": {"status": "completed"},
                "replays": {"status": "completed", "replay_ids": ["replay_a"]},
            }
        ),
        encoding="utf-8",
    )
    (run_002 / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "run_002",
                "created_at": "2026-04-04T00:20:00+00:00",
                "updated_at": "2026-04-04T00:30:00+00:00",
                "train": {"status": "completed"},
                "eval": {"status": "completed"},
                "replays": {"status": "completed", "replay_ids": ["replay_b"]},
            }
        ),
        encoding="utf-8",
    )
    _write_replay_bundle(run_001, "replay_a")
    _write_replay_bundle(run_002, "replay_b")
    active_run_file.write_text("run_002\n", encoding="utf-8")

    monkeypatch.setattr("backend.app.core.runs.RUNS_DIR", runs_dir)
    monkeypatch.setattr("backend.app.core.runs.ACTIVE_RUN_FILE", active_run_file)

    client = TestClient(app)

    runs_response = client.get("/replay/runs")
    assert runs_response.status_code == 200
    runs_payload = runs_response.json()
    assert [item["run_id"] for item in runs_payload["runs"]] == ["run_002", "run_001"]

    list_response = client.get("/replay/runs/run_001/list")
    assert list_response.status_code == 200
    assert list_response.json()["run_id"] == "run_001"
    assert [item["replay_id"] for item in list_response.json()["replays"]] == ["replay_a"]

    bundle_response = client.get("/replay/runs/run_001/replay_a/bundle")
    assert bundle_response.status_code == 200
    assert bundle_response.json()["run_id"] == "run_001"
    assert bundle_response.json()["replay_id"] == "replay_a"
