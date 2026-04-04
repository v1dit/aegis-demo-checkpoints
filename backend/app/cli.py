from __future__ import annotations

import argparse
import time
from pathlib import Path

from backend.app.core.paths import (
    CHECKPOINT_DIR,
    EVAL_REPORT_DIR,
    FIXTURES_DIR,
    REPLAY_DIR,
    ensure_artifact_dirs,
)
from backend.app.replay.packager import package_demo_replays, write_ws_mock_frames
from backend.app.rl.eval import acceptance_gate_status, evaluate_checkpoint, write_eval_report
from backend.app.rl.train import get_train_status, latest_completed_checkpoint, start_training_job
from backend.app.schemas.contracts import EvalRunRequest, TrainRunRequest
from backend.app.schemas.fixtures import write_contract_fixtures


def _latest_checkpoint_from_disk(checkpoint_dir: Path) -> str | None:
    checkpoints = sorted(checkpoint_dir.glob("ckpt_blue_main_*.json"))
    if not checkpoints:
        return None
    return checkpoints[-1].stem


def _run_train() -> None:
    request = TrainRunRequest(
        run_name="blue_train_main",
        seed=42,
        gpu_ids=[5, 6, 7],
        max_timesteps=3000000,
        config_profile="weekend_v1",
    )
    run_id = start_training_job(request=request, checkpoint_dir=CHECKPOINT_DIR)
    print(f"run_id={run_id}")

    while True:
        status = get_train_status(run_id)
        print(
            "status="
            f"{status.status} "
            f"phase={status.phase} "
            f"timesteps={status.timesteps} "
            f"metrics={status.learning_metrics}"
        )
        if status.status in {"completed", "failed"}:
            break
        time.sleep(0.25)


def _run_eval() -> None:
    checkpoint_id = (
        latest_completed_checkpoint()
        or _latest_checkpoint_from_disk(CHECKPOINT_DIR)
        or "checkpoint_blue_demo_best"
    )
    request = EvalRunRequest(
        checkpoint_id=checkpoint_id,
        suite_id="heldout_suite_v1",
        seeds=[1001, 1002, 1003, 1004],
    )
    eval_id = f"eval_cli_{int(time.time())}"
    report = evaluate_checkpoint(
        eval_id=eval_id,
        checkpoint_id=request.checkpoint_id,
        suite_id=request.suite_id,
        seeds=request.seeds,
        replay_root=REPLAY_DIR,
    )
    report_path = write_eval_report(report, EVAL_REPORT_DIR)
    gates = acceptance_gate_status(report)

    print(f"eval_report={report_path}")
    print(f"kpis={report.kpis.model_dump(mode='json')}")
    print(f"acceptance_gates={gates}")


def _package_replays() -> None:
    checkpoint_id = latest_completed_checkpoint() or "checkpoint_blue_demo_best"
    manifests = package_demo_replays(checkpoint_id=checkpoint_id, replay_root=REPLAY_DIR)
    ws_fixture = write_ws_mock_frames(REPLAY_DIR, FIXTURES_DIR / "ws_mock_frames")
    write_contract_fixtures(FIXTURES_DIR / "schema_examples")

    print(f"packaged={len(manifests)}")
    print(f"ws_fixture={ws_fixture}")


def _demo() -> None:
    _package_replays()
    if not (EVAL_REPORT_DIR / "eval_report_latest.json").exists():
        _run_eval()
    print(
        "Demo artifacts ready. Start API with: "
        "uv run uvicorn backend.app.main:app --host 0.0.0.0 --port 8000"
    )


def main() -> None:
    ensure_artifact_dirs()

    parser = argparse.ArgumentParser(description="PantherHacks Track A CLI")
    parser.add_argument("command", choices=["train", "eval", "package-replays", "demo"])
    args = parser.parse_args()

    if args.command == "train":
        _run_train()
    elif args.command == "eval":
        _run_eval()
    elif args.command == "package-replays":
        _package_replays()
    elif args.command == "demo":
        _demo()


if __name__ == "__main__":
    main()
