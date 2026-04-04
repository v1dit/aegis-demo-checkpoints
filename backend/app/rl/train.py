from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from backend.app.core.config import settings
from backend.app.core.ids import prefixed_id
from backend.app.core.runs import (
    ParentInfo,
    initialize_run_bundle,
    mirror_checkpoint_to_legacy,
    resolve_parent_info,
    run_stage_dirs,
    update_train_manifest,
)
from backend.app.core.state import shared_state
from backend.app.rl.rllib_runner import RLlibUnavailableError, run_ppo_training
from backend.app.schemas.contracts import TrainRunRequest, TrainStatusResponse

_train_counter = 0


def _next_run_id() -> str:
    global _train_counter
    _train_counter += 1
    return prefixed_id("run", _train_counter)


def _checkpoint_id_for_run(run_id: str) -> str:
    return f"ckpt_blue_main_{run_id.split('_')[-1]}"


def _runner_config(
    *,
    run_id: str,
    request: TrainRunRequest,
    checkpoint_output_dir: Path,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "seed": request.seed,
        "max_timesteps": request.max_timesteps,
        "checkpoint_output_dir": str(checkpoint_output_dir),
        "lr": settings.ppo_lr,
        "gamma": settings.ppo_gamma,
        "train_batch_size": settings.ppo_train_batch_size,
        "num_rollout_workers": settings.ppo_num_rollout_workers,
        "num_gpus": float(len(request.gpu_ids)),
        "horizon": settings.ppo_horizon,
        "scenario_id": settings.ppo_scenario_id,
        "red_stochastic_probability": settings.red_stochastic_probability,
    }


def _update_running_state(
    run_id: str,
    *,
    phase: str,
    timesteps: int,
    learning_metrics: dict[str, float],
) -> None:
    with shared_state.lock:
        shared_state.train_runs[run_id].update(
            {
                "status": "running",
                "phase": phase,
                "timesteps": timesteps,
                "learning_metrics": learning_metrics,
            }
        )
    update_train_manifest(
        run_id,
        status="running",
        phase=phase,
        timesteps=timesteps,
        learning_metrics=learning_metrics,
    )


def _checkpoint_payload(
    *,
    run_id: str,
    request: TrainRunRequest,
    parent_info: ParentInfo,
    checkpoint_id: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "checkpoint_id": checkpoint_id,
        "run_id": run_id,
        "seed": request.seed,
        "parent_run_id": parent_info.parent_run_id,
        "parent_checkpoint": parent_info.parent_checkpoint,
        "trainer": "rllib_ppo",
        "rllib_checkpoint_path": result.get("rllib_checkpoint_path"),
        "seed_strategy": result.get("seed_strategy", {}),
        "ppo_config": result.get("ppo_config", {}),
        "config_profile": request.config_profile,
        "gpu_ids": request.gpu_ids,
        "timesteps": int(result.get("timesteps_total", request.max_timesteps)),
        "learning_metrics": result.get("learning_metrics", {}),
    }


def _run_ppo_training_job(run_id: str, request: TrainRunRequest, checkpoint_dir: Path) -> None:
    _ = checkpoint_dir
    run_dirs = run_stage_dirs(run_id)
    manifest = initialize_run_bundle(
        run_id=run_id,
        request_payload=request.model_dump(mode="json"),
        parent_info=resolve_parent_info(request.fresh_start),
        fresh_start=request.fresh_start,
    )
    parent_info = ParentInfo(
        parent_run_id=manifest.get("parent_run_id"),
        parent_checkpoint=manifest.get("parent_checkpoint"),
    )

    with shared_state.lock:
        shared_state.train_runs[run_id]["parent_run_id"] = parent_info.parent_run_id
        shared_state.train_runs[run_id]["parent_checkpoint"] = parent_info.parent_checkpoint

    try:
        _update_running_state(
            run_id,
            phase="initializing",
            timesteps=0,
            learning_metrics={},
        )
        result = run_ppo_training(
            _runner_config(
                run_id=run_id,
                request=request,
                checkpoint_output_dir=run_dirs["train"] / "rllib",
            )
        )

        for row in result.get("iterations", []):
            metrics = {
                "episode_reward_mean": round(float(row.get("episode_reward_mean", 0.0)), 6),
                "episode_len_mean": round(float(row.get("episode_len_mean", 0.0)), 6),
                "timesteps_total": int(row.get("timesteps_total", 0)),
            }
            _update_running_state(
                run_id,
                phase="policy_optimization",
                timesteps=int(row.get("timesteps_total", 0)),
                learning_metrics=metrics,
            )

        learning_metrics = {
            key: float(value)
            for key, value in result.get("learning_metrics", {}).items()
            if isinstance(value, int | float)
        }
        timesteps_total = int(result.get("timesteps_total", request.max_timesteps))
        checkpoint_id = _checkpoint_id_for_run(run_id)
        checkpoint_path = run_dirs["train"] / f"{checkpoint_id}.json"
        checkpoint_path.write_text(
            json.dumps(
                _checkpoint_payload(
                    run_id=run_id,
                    request=request,
                    parent_info=parent_info,
                    checkpoint_id=checkpoint_id,
                    result=result,
                ),
                indent=2,
            ),
            encoding="utf-8",
        )

        with shared_state.lock:
            shared_state.train_runs[run_id].update(
                {
                    "status": "completed",
                    "phase": "completed",
                    "timesteps": timesteps_total,
                    "checkpoint_path": str(checkpoint_path),
                    "checkpoint_id": checkpoint_id,
                    "learning_metrics": learning_metrics,
                }
            )

        update_train_manifest(
            run_id,
            status="completed",
            phase="completed",
            timesteps=timesteps_total,
            learning_metrics=learning_metrics,
            checkpoint_id=checkpoint_id,
            checkpoint_path=str(checkpoint_path),
        )
        mirror_checkpoint_to_legacy(checkpoint_path, checkpoint_id)
    except RLlibUnavailableError as exc:
        with shared_state.lock:
            shared_state.train_runs[run_id].update(
                {
                    "status": "failed",
                    "phase": "failed",
                    "error": str(exc),
                }
            )
        update_train_manifest(
            run_id,
            status="failed",
            phase="failed",
            timesteps=shared_state.train_runs[run_id].get("timesteps", 0),
            learning_metrics=shared_state.train_runs[run_id].get("learning_metrics", {}),
        )
    except Exception as exc:  # pragma: no cover - defensive
        with shared_state.lock:
            shared_state.train_runs[run_id].update(
                {
                    "status": "failed",
                    "phase": "failed",
                    "error": str(exc),
                }
            )
        update_train_manifest(
            run_id,
            status="failed",
            phase="failed",
            timesteps=shared_state.train_runs[run_id].get("timesteps", 0),
            learning_metrics=shared_state.train_runs[run_id].get("learning_metrics", {}),
        )


def start_training_job(request: TrainRunRequest, checkpoint_dir: Path) -> tuple[str, ParentInfo]:
    parent_info = resolve_parent_info(request.fresh_start)
    run_id = request.run_id or _next_run_id()
    with shared_state.lock:
        shared_state.train_runs[run_id] = {
            "run_id": run_id,
            "status": "queued",
            "phase": "queued",
            "timesteps": 0,
            "checkpoint_path": None,
            "learning_metrics": {},
            "request": request.model_dump(mode="json"),
            "parent_run_id": parent_info.parent_run_id,
            "parent_checkpoint": parent_info.parent_checkpoint,
        }

    thread = threading.Thread(
        target=_run_ppo_training_job,
        args=(run_id, request, checkpoint_dir),
        daemon=True,
        name=f"train-{run_id}",
    )
    thread.start()
    return run_id, parent_info


def latest_completed_checkpoint() -> str | None:
    with shared_state.lock:
        completed = [
            run
            for run in shared_state.train_runs.values()
            if run.get("status") == "completed" and run.get("checkpoint_id")
        ]
    if not completed:
        return None
    completed.sort(key=lambda row: row["run_id"])
    return completed[-1]["checkpoint_id"]


def get_train_status(run_id: str) -> TrainStatusResponse:
    with shared_state.lock:
        run = shared_state.train_runs.get(run_id)
    if run is None:
        raise KeyError(run_id)
    return TrainStatusResponse(
        run_id=run_id,
        status=run["status"],
        phase=run["phase"],
        timesteps=run["timesteps"],
        parent_run_id=run.get("parent_run_id"),
        parent_checkpoint=run.get("parent_checkpoint"),
        checkpoint_path=run.get("checkpoint_path"),
        learning_metrics=run.get("learning_metrics", {}),
    )
