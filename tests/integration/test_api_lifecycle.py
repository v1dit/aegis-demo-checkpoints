import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.schemas.contracts import EvalKpis, EvalReport


def _mock_run_ppo_training(config: dict[str, Any]) -> dict[str, Any]:
    checkpoint_path = Path(config["checkpoint_output_dir"]) / "rllib_ckpt"
    checkpoint_path.mkdir(parents=True, exist_ok=True)
    return {
        "trainer": "rllib_ppo",
        "status": "completed",
        "timesteps_total": int(config["max_timesteps"]),
        "rllib_checkpoint_path": str(checkpoint_path),
        "seed_strategy": {
            "base_seed": int(config["seed"]),
            "episode_seed_mode": "per-episode-randomized",
        },
        "ppo_config": {
            "lr": float(config["lr"]),
            "gamma": float(config["gamma"]),
            "train_batch_size": int(config["train_batch_size"]),
            "num_rollout_workers": int(config["num_rollout_workers"]),
        },
        "learning_metrics": {
            "episode_reward_mean": 1.1,
            "episode_len_mean": 42.0,
            "timesteps_total": int(config["max_timesteps"]),
        },
    }


def _mock_evaluate_checkpoint(
    *,
    eval_id: str,
    checkpoint_id: str,
    suite_id: str,
    seeds: list[int],
    replay_root: Path,
    run_id: str | None = None,
) -> EvalReport:
    _ = checkpoint_id
    _ = seeds
    _ = replay_root
    return EvalReport(
        eval_id=eval_id,
        run_id=run_id,
        suite_id=suite_id,
        kpis=EvalKpis(
            damage_reduction_vs_no_defense=0.3,
            damage_reduction_vs_rule_based=0.2,
            detection_latency_improvement_vs_rule_based=0.25,
        ),
        per_scenario=[],
    )


def test_train_eval_replay_lifecycle(tmp_path, monkeypatch) -> None:
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

    monkeypatch.setattr("backend.app.rl.train.run_ppo_training", _mock_run_ppo_training)
    monkeypatch.setattr("backend.app.rl.eval_jobs.evaluate_checkpoint", _mock_evaluate_checkpoint)

    client = TestClient(app)

    train_resp = client.post(
        "/train/run",
        json={
            "run_name": "blue_train_main",
            "seed": 42,
            "gpu_ids": [5, 6, 7],
            "max_timesteps": 2000,
            "config_profile": "weekend_v1",
        },
    )
    assert train_resp.status_code == 200
    run_id = train_resp.json()["run_id"]

    status = None
    for _ in range(60):
        status_resp = client.get(f"/train/status/{run_id}")
        assert status_resp.status_code == 200
        status = status_resp.json()
        if status["status"] in {"completed", "failed"}:
            break
        time.sleep(0.05)

    assert status is not None
    assert status["status"] == "completed"

    checkpoint_id = "checkpoint_blue_demo_best"
    if status["checkpoint_path"]:
        checkpoint_id = status["checkpoint_path"].split("/")[-1].replace(".json", "")

    eval_resp = client.post(
        "/eval/run",
        json={
            "checkpoint_id": checkpoint_id,
            "suite_id": "heldout_suite_v1",
            "seeds": [1001, 1002, 1003, 1004],
        },
    )
    assert eval_resp.status_code == 200
    eval_id = eval_resp.json()["eval_id"]

    report = None
    for _ in range(120):
        report_resp = client.get(f"/eval/report/{eval_id}")
        if report_resp.status_code == 200:
            report = report_resp.json()
            break
        assert report_resp.status_code == 409
        time.sleep(0.05)

    assert report is not None
    assert "kpis" in report
    assert "damage_reduction_vs_no_defense" in report["kpis"]

    replay_list = client.get("/replay/list")
    assert replay_list.status_code == 200
