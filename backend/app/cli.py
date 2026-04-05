from __future__ import annotations

import argparse
import os
import random
import time

from backend.app.core.paths import CHECKPOINT_DIR, FIXTURES_DIR, ensure_artifact_dirs
from backend.app.core.runs import (
    compute_improvement_delta,
    get_active_run_id,
    get_parent_kpis,
    load_manifest,
    mirror_eval_to_legacy,
    resolve_canonical_run_id,
    run_stage_dirs,
    set_active_run_id,
    update_eval_manifest,
)
from backend.app.replay.packager import package_demo_replays, write_ws_mock_frames
from backend.app.rl.eval import acceptance_gate_status, evaluate_checkpoint, write_eval_report
from backend.app.rl.train import get_train_status, latest_completed_checkpoint, start_training_job
from backend.app.schemas.contracts import EvalRunRequest, TrainRunRequest
from backend.app.schemas.fixtures import write_contract_fixtures


def _parse_seed_list(value: str | None, fallback: list[int]) -> list[int]:
    if value is None:
        return fallback
    stripped = value.strip()
    if not stripped:
        return fallback
    return [int(chunk.strip()) for chunk in stripped.split(",") if chunk.strip()]


def _latest_checkpoint_from_run(run_id: str | None) -> str | None:
    if not run_id:
        return None
    run_dirs = run_stage_dirs(run_id)
    checkpoints = sorted(run_dirs["train"].glob("ckpt_blue_main_*.json"))
    if not checkpoints:
        return None
    return checkpoints[-1].stem


def _run_train(run_id: str | None, fresh_start: bool, seed: int | None) -> str:
    effective_seed = seed if seed is not None else random.randint(0, 100_000)
    if seed is None:
        print(f"seed={effective_seed} (auto-generated)")
    request = TrainRunRequest(
        run_name="blue_train_main",
        seed=effective_seed,
        gpu_ids=[5, 6, 7],
        max_timesteps=3000000,
        config_profile="weekend_v1",
        run_id=run_id,
        fresh_start=fresh_start,
    )
    run_id, parent_info = start_training_job(request=request, checkpoint_dir=CHECKPOINT_DIR)
    print(
        f"run_id={run_id} parent_run_id={parent_info.parent_run_id} "
        f"parent_checkpoint={parent_info.parent_checkpoint}"
    )

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
    return run_id


def _run_eval(
    run_id: str | None,
    suite_id: str | None = None,
    eval_seeds: str | None = None,
) -> str:
    resolved_run = run_id or resolve_canonical_run_id() or get_active_run_id()
    resolved_suite_id = suite_id or os.getenv("PPO_EVAL_SUITE_ID", "heldout_suite_v1")
    resolved_eval_seeds = _parse_seed_list(
        eval_seeds or os.getenv("PPO_EVAL_SEEDS"),
        fallback=[1001, 1002, 1003, 1004],
    )
    checkpoint_id = (
        latest_completed_checkpoint()
        or _latest_checkpoint_from_run(resolved_run)
        or "checkpoint_blue_demo_best"
    )
    request = EvalRunRequest(
        checkpoint_id=checkpoint_id,
        suite_id=resolved_suite_id,
        seeds=resolved_eval_seeds,
        run_id=resolved_run,
    )
    eval_id = f"eval_cli_{int(time.time())}"
    run_dirs = run_stage_dirs(resolved_run or "run_adhoc")
    report = evaluate_checkpoint(
        eval_id=eval_id,
        checkpoint_id=request.checkpoint_id,
        suite_id=request.suite_id,
        seeds=request.seeds,
        replay_root=run_dirs["replays"],
        run_id=request.run_id,
    )
    report_path = write_eval_report(report, run_dirs["eval"])
    gates = acceptance_gate_status(report)
    if report_path.exists():
        mirror_eval_to_legacy(report_path)
    parent_run_id = None
    try:
        parent_run_id = load_manifest(resolved_run)["parent_run_id"] if resolved_run else None
    except FileNotFoundError:
        parent_run_id = None
    delta = compute_improvement_delta(
        report.kpis.model_dump(mode="json"),
        get_parent_kpis(parent_run_id),
    )
    report.improvement_delta_vs_parent = delta
    if resolved_run:
        try:
            update_eval_manifest(
                resolved_run,
                eval_id=eval_id,
                status="completed",
                report_path=str(report_path),
                kpis=report.kpis.model_dump(mode="json"),
                gates=gates,
                improvement_delta=delta,
            )
        except FileNotFoundError:
            pass

    print(f"run_id={resolved_run}")
    print(f"eval_report={report_path}")
    print(f"kpis={report.kpis.model_dump(mode='json')}")
    print(f"acceptance_gates={gates}")
    return resolved_run or "run_adhoc"


def _package_replays(run_id: str | None = None) -> None:
    resolved_run = run_id or resolve_canonical_run_id() or get_active_run_id()
    checkpoint_id = latest_completed_checkpoint() or _latest_checkpoint_from_run(resolved_run)
    checkpoint_id = checkpoint_id or "checkpoint_blue_demo_best"
    if resolved_run:
        set_active_run_id(resolved_run)
    run_dirs = run_stage_dirs(resolved_run or "run_adhoc")
    manifests = package_demo_replays(
        checkpoint_id=checkpoint_id,
        replay_root=run_dirs["replays"],
        run_id=resolved_run,
    )
    ws_fixture = write_ws_mock_frames(run_dirs["replays"], FIXTURES_DIR / "ws_mock_frames")
    write_contract_fixtures(FIXTURES_DIR / "schema_examples")

    print(f"run_id={resolved_run}")
    print(f"packaged={len(manifests)}")
    print(f"ws_fixture={ws_fixture}")


def _demo(run_id: str | None) -> None:
    resolved_run = run_id or resolve_canonical_run_id() or get_active_run_id()
    _package_replays(resolved_run)
    _run_eval(resolved_run, suite_id=None, eval_seeds=None)
    print(
        "Demo artifacts ready. Start API with: "
        "uv run uvicorn backend.app.main:app --host 0.0.0.0 --port 8000"
    )


def main() -> None:
    ensure_artifact_dirs()

    parser = argparse.ArgumentParser(description="PantherHacks Track A CLI")
    parser.add_argument("command", choices=["train", "eval", "package-replays", "demo"])
    parser.add_argument("--run-id", dest="run_id", default=None)
    parser.add_argument("--fresh-start", action="store_true")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--suite-id", default=None)
    parser.add_argument(
        "--eval-seeds",
        default=None,
        help="Comma-separated eval seeds, e.g. 1001,1002,1003,1004",
    )
    args = parser.parse_args()

    if args.command == "train":
        _run_train(run_id=args.run_id, fresh_start=args.fresh_start, seed=args.seed)
    elif args.command == "eval":
        _run_eval(run_id=args.run_id, suite_id=args.suite_id, eval_seeds=args.eval_seeds)
    elif args.command == "package-replays":
        _package_replays(run_id=args.run_id)
    elif args.command == "demo":
        _demo(run_id=args.run_id)


if __name__ == "__main__":
    main()
