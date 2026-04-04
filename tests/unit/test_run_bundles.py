from __future__ import annotations

import json
import time

from backend.app.core.runs import get_active_run_id, load_manifest, run_stage_dirs
from backend.app.rl.eval_jobs import start_eval_job
from backend.app.rl.train import get_train_status, start_training_job
from backend.app.schemas.contracts import EvalRunRequest, TrainRunRequest


def _wait_train_completed(run_id: str) -> None:
    for _ in range(200):
        status = get_train_status(run_id)
        if status.status in {"completed", "failed"}:
            assert status.status == "completed"
            return
        time.sleep(0.05)
    raise AssertionError("training did not complete")


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
    assert run2_ckpt["policy_bias"] > run1_ckpt["policy_bias"]
    assert get_active_run_id() == run2
