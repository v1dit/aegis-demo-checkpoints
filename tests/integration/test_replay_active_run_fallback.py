from __future__ import annotations

import json

from fastapi.testclient import TestClient

from backend.app.main import app


def test_replay_list_falls_back_when_active_run_is_stale(tmp_path, monkeypatch) -> None:
    runs_dir = tmp_path / "runs"
    active_run_file = runs_dir / ".active_run"
    replay_root = runs_dir / "run_002" / "replays" / "replay_hero_01"
    replay_root.mkdir(parents=True, exist_ok=True)

    manifest = {
        "run_id": "run_002",
        "train": {"status": "completed"},
        "eval": {"status": "completed", "gates": {}},
        "replays": {"status": "completed", "replay_ids": ["replay_hero_01"]},
    }
    run_manifest_path = replay_root.parent.parent / "manifest.json"
    run_manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    replay_manifest = {
        "replay_id": "replay_hero_01",
        "scenario_id": "scenario_unseen_web_rce",
        "seed": 1003,
        "checkpoint_id": "ckpt_blue_main_001",
        "duration_steps": 200,
        "files": {
            "events": "events.jsonl",
            "topology": "topology_snapshots.json",
            "metrics": "metrics.json",
        },
    }
    (replay_root / "manifest.json").write_text(json.dumps(replay_manifest), encoding="utf-8")

    runs_dir.mkdir(parents=True, exist_ok=True)
    active_run_file.write_text("run_999\n", encoding="utf-8")

    monkeypatch.setattr("backend.app.core.runs.RUNS_DIR", runs_dir)
    monkeypatch.setattr("backend.app.core.runs.ACTIVE_RUN_FILE", active_run_file)

    client = TestClient(app)
    response = client.get("/replay/list")
    assert response.status_code == 200

    payload = response.json()
    assert payload["run_id"] == "run_002"
    assert [item["replay_id"] for item in payload["replays"]] == ["replay_hero_01"]
