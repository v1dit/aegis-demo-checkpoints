from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from backend.app.core.state import shared_state
from backend.app.rl.rllib_runner import RLlibUnavailableError
from backend.app.rl.train import get_train_status, start_training_job
from backend.app.schemas.contracts import TrainRunRequest


def _wait_until_terminal(run_id: str) -> str:
    for _ in range(200):
        status = get_train_status(run_id)
        if status.status in {"completed", "failed"}:
            return status.status
        time.sleep(0.05)
    raise AssertionError("training job did not reach a terminal state")


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
            "episode_reward_mean": 1.0,
            "episode_len_mean": 20.0,
            "timesteps_total": int(config["max_timesteps"]),
        },
    }


def _mock_preflight_entropy_collapse(config: dict[str, Any]) -> dict[str, Any]:
    if int(config.get("max_iterations", 0)) == 5:
        return {
            "trainer": "rllib_ppo",
            "status": "completed",
            "timesteps_total": int(config["max_timesteps"]),
            "rllib_checkpoint_path": str(Path(config["checkpoint_output_dir"]) / "preflight_ckpt"),
            "learning_metrics": {
                "episode_reward_mean": 0.2,
                "timesteps_total": int(config["max_timesteps"]),
                "policy_entropy": 0.0,
            },
            "reward_shaping_probe_repeat_penalties": 2,
        }
    return _mock_run_ppo_training(config)


def _write_manifest(runs_dir: Path, run_id: str) -> None:
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "manifest.json").write_text(json.dumps({"run_id": run_id}), encoding="utf-8")


def test_training_job_persists_ppo_checkpoint_metadata(tmp_path, monkeypatch) -> None:
    with shared_state.lock:
        shared_state.train_runs.clear()
    monkeypatch.setattr("backend.app.core.paths.RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr("backend.app.core.runs.RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr("backend.app.core.runs.CHECKPOINT_DIR", tmp_path / "artifacts/checkpoints")
    monkeypatch.setattr("backend.app.rl.train.run_ppo_training", _mock_run_ppo_training)

    request = TrainRunRequest(
        run_name="blue_train_main",
        seed=77,
        gpu_ids=[0],
        max_timesteps=1200,
        config_profile="weekend_v1",
        fresh_start=True,
    )
    run_id, _ = start_training_job(request=request, checkpoint_dir=tmp_path / "legacy/checkpoints")

    assert _wait_until_terminal(run_id) == "completed"

    checkpoint_id = f"ckpt_blue_main_{run_id.split('_')[-1]}"
    checkpoint_file = tmp_path / "runs" / run_id / "train" / f"{checkpoint_id}.json"
    payload = json.loads(checkpoint_file.read_text(encoding="utf-8"))
    assert payload["trainer"] == "rllib_ppo"
    assert payload["seed_strategy"]["episode_seed_mode"] == "per-episode-randomized"
    assert "rllib_checkpoint_path" in payload

    status = get_train_status(run_id)
    assert "episode_reward_mean" in status.learning_metrics


def test_training_job_fails_when_rllib_is_unavailable(tmp_path, monkeypatch) -> None:
    with shared_state.lock:
        shared_state.train_runs.clear()
    monkeypatch.setattr("backend.app.core.paths.RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr("backend.app.core.runs.RUNS_DIR", tmp_path / "runs")

    def _raise_unavailable(_config: dict[str, Any]) -> dict[str, Any]:
        raise RLlibUnavailableError("ray[rllib] is not installed")

    monkeypatch.setattr("backend.app.rl.train.run_ppo_training", _raise_unavailable)

    request = TrainRunRequest(
        run_name="blue_train_main",
        seed=91,
        gpu_ids=[0],
        max_timesteps=600,
        config_profile="weekend_v1",
        fresh_start=True,
    )
    run_id, _ = start_training_job(request=request, checkpoint_dir=tmp_path / "legacy/checkpoints")
    assert _wait_until_terminal(run_id) == "failed"

    with shared_state.lock:
        error = str(shared_state.train_runs[run_id].get("error", ""))
    assert "ray[rllib]" in error


def test_training_job_run_id_starts_at_run_001(tmp_path, monkeypatch) -> None:
    with shared_state.lock:
        shared_state.train_runs.clear()
    monkeypatch.setattr("backend.app.core.paths.RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr("backend.app.core.runs.RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr("backend.app.core.runs.CHECKPOINT_DIR", tmp_path / "artifacts/checkpoints")
    monkeypatch.setattr("backend.app.rl.train.run_ppo_training", _mock_run_ppo_training)

    request = TrainRunRequest(
        run_name="blue_train_main",
        seed=12,
        gpu_ids=[0],
        max_timesteps=20,
        config_profile="weekend_v1",
        fresh_start=True,
    )
    run_id, _ = start_training_job(request=request, checkpoint_dir=tmp_path / "legacy/checkpoints")
    assert run_id == "run_001"
    assert _wait_until_terminal(run_id) == "completed"


def test_training_job_run_id_continues_from_highest_numeric_run(tmp_path, monkeypatch) -> None:
    with shared_state.lock:
        shared_state.train_runs.clear()
    runs_dir = tmp_path / "runs"
    _write_manifest(runs_dir, "run_001")
    _write_manifest(runs_dir, "run_002")
    _write_manifest(runs_dir, "run_20260404_080336_001")
    _write_manifest(runs_dir, "not_a_run")

    monkeypatch.setattr("backend.app.core.paths.RUNS_DIR", runs_dir)
    monkeypatch.setattr("backend.app.core.runs.RUNS_DIR", runs_dir)
    monkeypatch.setattr("backend.app.core.runs.CHECKPOINT_DIR", tmp_path / "artifacts/checkpoints")
    monkeypatch.setattr("backend.app.rl.train.run_ppo_training", _mock_run_ppo_training)

    request = TrainRunRequest(
        run_name="blue_train_main",
        seed=13,
        gpu_ids=[0],
        max_timesteps=20,
        config_profile="weekend_v1",
        fresh_start=True,
    )
    run_id, _ = start_training_job(request=request, checkpoint_dir=tmp_path / "legacy/checkpoints")
    assert run_id == "run_003"
    assert _wait_until_terminal(run_id) == "completed"


def test_heavy_training_is_blocked_when_preflight_entropy_collapses(tmp_path, monkeypatch) -> None:
    with shared_state.lock:
        shared_state.train_runs.clear()
    monkeypatch.setattr("backend.app.core.paths.RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr("backend.app.core.runs.RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr("backend.app.core.runs.CHECKPOINT_DIR", tmp_path / "artifacts/checkpoints")
    monkeypatch.setattr("backend.app.rl.train.run_ppo_training", _mock_preflight_entropy_collapse)
    monkeypatch.setattr(
        "backend.app.rl.train.settings.ppo_heavy_timesteps_threshold",
        1000,
        raising=False,
    )
    monkeypatch.setattr(
        "backend.app.rl.train.settings.ppo_preflight_iterations",
        5,
        raising=False,
    )
    monkeypatch.setattr(
        "backend.app.rl.train.settings.ppo_preflight_min_entropy",
        0.01,
        raising=False,
    )

    request = TrainRunRequest(
        run_name="blue_train_main",
        seed=17,
        gpu_ids=[0],
        max_timesteps=5000,
        config_profile="weekend_v1",
        fresh_start=True,
    )
    run_id, _ = start_training_job(request=request, checkpoint_dir=tmp_path / "legacy/checkpoints")
    assert _wait_until_terminal(run_id) == "failed"

    with shared_state.lock:
        error = str(shared_state.train_runs[run_id].get("error", ""))
    assert "preflight" in error.lower()
