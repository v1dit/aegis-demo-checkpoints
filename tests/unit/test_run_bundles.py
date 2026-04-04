from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from backend.app.core.runs import get_active_run_id, load_manifest, run_stage_dirs
from backend.app.rl.eval_jobs import start_eval_job
from backend.app.rl.train import get_train_status, start_training_job
from backend.app.schemas.contracts import EvalKpis, EvalReport, EvalRunRequest, TrainRunRequest


def _wait_train_completed(run_id: str) -> None:
    for _ in range(200):
        status = get_train_status(run_id)
        if status.status in {"completed", "failed"}:
            assert status.status == "completed"
            return
        time.sleep(0.05)
    raise AssertionError("training did not complete")


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
            "episode_reward_mean": 1.2,
            "episode_len_mean": 37.0,
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


def test_run_bundle_structure_and_lineage(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("backend.app.core.paths.RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr("backend.app.core.runs.RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(
        "backend.app.core.runs.CHECKPOINT_DIR",
        tmp_path / "artifacts/checkpoints",
    )
    monkeypatch.setattr(
        "backend.app.core.runs.EVAL_REPORT_DIR",
        tmp_path / "artifacts/eval_reports",
    )
    monkeypatch.setattr("backend.app.core.runs.REPLAY_DIR", tmp_path / "artifacts/replays")
    monkeypatch.setattr("backend.app.rl.train.run_ppo_training", _mock_run_ppo_training)
    monkeypatch.setattr("backend.app.rl.eval_jobs.evaluate_checkpoint", _mock_evaluate_checkpoint)

    request = TrainRunRequest(
        run_name="blue_train_main",
        seed=42,
        gpu_ids=[5, 6, 7],
        max_timesteps=5000,
        config_profile="weekend_v1",
        fresh_start=True,
    )
    run1, _ = start_training_job(request=request, checkpoint_dir=tmp_path / "legacy/checkpoints")
    _wait_train_completed(run1)

    start_eval_job(
        request=EvalRunRequest(
            checkpoint_id=f"ckpt_blue_main_{run1.split('_')[-1]}",
            suite_id="heldout_suite_v1",
            seeds=[1001, 1002, 1003, 1004],
            run_id=run1,
        ),
        replay_dir=tmp_path / "legacy/replays",
        report_dir=tmp_path / "legacy/eval_reports",
    )

    for _ in range(200):
        manifest = load_manifest(run1)
        if manifest["eval"]["status"] == "completed":
            break
        time.sleep(0.05)

    dirs = run_stage_dirs(run1)
    assert (dirs["train"]).exists()
    assert (dirs["eval"]).exists()
    assert (dirs["replays"]).exists()

    request2 = TrainRunRequest(
        run_name="blue_train_main",
        seed=42,
        gpu_ids=[5, 6, 7],
        max_timesteps=5000,
        config_profile="weekend_v1",
        fresh_start=False,
    )
    run2, parent = start_training_job(
        request=request2,
        checkpoint_dir=tmp_path / "legacy/checkpoints",
    )
    _wait_train_completed(run2)

    manifest2 = load_manifest(run2)
    run1_ckpt_name = f"ckpt_blue_main_{run1.split('_')[-1]}.json"
    run2_ckpt_name = f"ckpt_blue_main_{run2.split('_')[-1]}.json"
    run1_ckpt = json.loads((run_stage_dirs(run1)["train"] / run1_ckpt_name).read_text())
    run2_ckpt = json.loads((run_stage_dirs(run2)["train"] / run2_ckpt_name).read_text())
    assert parent.parent_run_id == run1
    assert manifest2["parent_run_id"] == run1
    assert run1_ckpt["trainer"] == "rllib_ppo"
    assert run2_ckpt["trainer"] == "rllib_ppo"
    assert "policy_bias" not in run2_ckpt
    assert "rllib_checkpoint_path" in run2_ckpt
    assert get_active_run_id() == run2
