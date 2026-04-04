from __future__ import annotations

import json
import math
import threading
from pathlib import Path
from typing import Any

from backend.app.core.config import settings
from backend.app.core.ids import next_sequential_id
from backend.app.core.runs import (
    ParentInfo,
    initialize_run_bundle,
    list_run_ids,
    mirror_checkpoint_to_legacy,
    resolve_parent_info,
    run_stage_dirs,
    update_train_manifest,
)
from backend.app.core.state import shared_state
from backend.app.rl.rllib_runner import (
    RLlibUnavailableError,
    preflight_gate_status,
    run_ppo_training,
)
from backend.app.schemas.contracts import TrainRunRequest, TrainStatusResponse

def _next_run_id(existing_ids: list[str]) -> str:
    return next_sequential_id(existing_ids, prefix="run", min_start=1)


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


def _preflight_config(
    *,
    run_id: str,
    request: TrainRunRequest,
    checkpoint_output_dir: Path,
) -> dict[str, Any]:
    config = _runner_config(
        run_id=run_id,
        request=request,
        checkpoint_output_dir=checkpoint_output_dir,
    )
    config["max_iterations"] = settings.ppo_preflight_iterations
    config["max_timesteps"] = min(
        request.max_timesteps,
        settings.ppo_preflight_iterations * settings.ppo_train_batch_size,
    )
    return config


def _requires_preflight_gate(request: TrainRunRequest) -> bool:
    if not settings.ppo_require_preflight_gate:
        return False
    return request.max_timesteps >= settings.ppo_heavy_timesteps_threshold


def _preflight_learning_metrics(result: dict[str, Any]) -> dict[str, float]:
    metrics = result.get("learning_metrics", {})
    if not isinstance(metrics, dict):
        return {}
    payload = {
        "preflight_episode_reward_mean": float(metrics.get("episode_reward_mean", 0.0)),
        "preflight_timesteps_total": float(metrics.get("timesteps_total", 0.0)),
        "preflight_policy_entropy": float(metrics.get("policy_entropy", 0.0)),
        "preflight_prevention_events": float(metrics.get("prevention_events", 0.0)),
        "preflight_repeat_penalty_events": float(metrics.get("repeat_penalty_events", 0.0)),
    }
    payload["preflight_repeat_penalty_probe"] = float(
        result.get("reward_shaping_probe_repeat_penalties", 0.0)
    )
    return payload


def _require_finite_metrics(metrics: dict[str, float]) -> list[str]:
    invalid: list[str] = []
    for key, value in metrics.items():
        if not math.isfinite(float(value)):
            invalid.append(key)
    return invalid


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
        if _requires_preflight_gate(request):
            _update_running_state(
                run_id,
                phase="preflight",
                timesteps=0,
                learning_metrics={"preflight_started": 1.0},
            )
            preflight_result = run_ppo_training(
                _preflight_config(
                    run_id=run_id,
                    request=request,
                    checkpoint_output_dir=run_dirs["train"] / "preflight",
                )
            )
            gate = preflight_gate_status(
                preflight_result,
                min_entropy=settings.ppo_preflight_min_entropy,
            )
            preflight_metrics = _preflight_learning_metrics(preflight_result)
            invalid_metrics = _require_finite_metrics(preflight_metrics)
            if invalid_metrics:
                gate.errors.append(f"non_finite_metrics:{','.join(sorted(invalid_metrics))}")
            _update_running_state(
                run_id,
                phase="preflight_completed",
                timesteps=int(preflight_metrics.get("preflight_timesteps_total", 0.0)),
                learning_metrics=preflight_metrics,
            )
            if not gate.passed:
                raise RuntimeError(f"Preflight gate failed: {', '.join(gate.errors)}")

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
    with shared_state.lock:
        existing_ids = list_run_ids() + list(shared_state.train_runs.keys())
        run_id = request.run_id or _next_run_id(existing_ids)
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
