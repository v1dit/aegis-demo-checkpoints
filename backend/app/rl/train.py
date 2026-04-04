from __future__ import annotations

import json
import random
import threading
import time
from pathlib import Path

from backend.app.core.ids import prefixed_id
from backend.app.core.runs import (
    ParentInfo,
    initialize_run_bundle,
    mirror_checkpoint_to_legacy,
    read_checkpoint_payload,
    resolve_parent_info,
    run_stage_dirs,
    update_train_manifest,
)
from backend.app.core.state import shared_state
from backend.app.schemas.contracts import TrainRunRequest, TrainStatusResponse

_train_counter = 0


def _next_run_id() -> str:
    global _train_counter
    _train_counter += 1
    return prefixed_id("run", _train_counter)


def _checkpoint_id_for_run(run_id: str) -> str:
    return f"ckpt_blue_main_{run_id.split('_')[-1]}"


def _training_bias(parent_info: ParentInfo, request_seed: int) -> float:
    rng = random.Random(request_seed)
    bias = 0.78 + rng.random() * 0.08
    if parent_info.parent_checkpoint:
        parent_payload = read_checkpoint_payload(
            parent_info.parent_checkpoint,
            parent_info.parent_run_id,
        )
        parent_bias = float(parent_payload.get("policy_bias", bias)) if parent_payload else bias
        # Simulate policy continuation benefit when not doing a fresh start.
        bias = parent_bias + 0.02
    return round(min(0.96, bias), 4)


def _run_simulated_training(run_id: str, request: TrainRunRequest, checkpoint_dir: Path) -> None:
    rng = random.Random(request.seed)
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

    try:
        with shared_state.lock:
            shared_state.train_runs[run_id]["status"] = "running"
            shared_state.train_runs[run_id]["phase"] = "warmup"
            shared_state.train_runs[run_id]["parent_run_id"] = parent_info.parent_run_id
            shared_state.train_runs[run_id]["parent_checkpoint"] = parent_info.parent_checkpoint

        max_steps = request.max_timesteps
        chunk = max(1, max_steps // 12)
        timesteps = 0

        for phase in [
            "warmup",
            "policy_optimization",
            "value_stabilization",
            "evaluation",
            "checkpointing",
        ]:
            for _ in range(2):
                timesteps = min(max_steps, timesteps + chunk)
                pressure = max(0.01, 1.2 - (timesteps / max_steps) + rng.random() * 0.03)
                attack_rate = max(0.05, 0.9 - (timesteps / max_steps) * 0.65 + rng.random() * 0.02)
                latency = max(35.0, 230.0 - (timesteps / max_steps) * 150.0 + rng.random() * 8.0)
                learning_metrics = {
                    "blue_pressure_score": round(pressure, 4),
                    "attack_success_rate": round(attack_rate, 4),
                    "detection_latency_ms": round(latency, 2),
                }
                with shared_state.lock:
                    shared_state.train_runs[run_id].update(
                        {
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
                time.sleep(0.08)

        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        checkpoint_id = _checkpoint_id_for_run(run_id)
        checkpoint_path = run_dirs["train"] / f"{checkpoint_id}.json"
        checkpoint_payload = {
            "checkpoint_id": checkpoint_id,
            "run_id": run_id,
            "seed": request.seed,
            "parent_run_id": parent_info.parent_run_id,
            "parent_checkpoint": parent_info.parent_checkpoint,
            "policy_bias": _training_bias(parent_info, request.seed),
            "config_profile": request.config_profile,
            "gpu_ids": request.gpu_ids,
            "timesteps": max_steps,
        }
        checkpoint_path.write_text(json.dumps(checkpoint_payload, indent=2), encoding="utf-8")

        with shared_state.lock:
            shared_state.train_runs[run_id].update(
                {
                    "status": "completed",
                    "phase": "completed",
                    "timesteps": max_steps,
                    "checkpoint_path": str(checkpoint_path),
                    "checkpoint_id": checkpoint_id,
                }
            )

        update_train_manifest(
            run_id,
            status="completed",
            phase="completed",
            timesteps=max_steps,
            learning_metrics=shared_state.train_runs[run_id].get("learning_metrics", {}),
            checkpoint_id=checkpoint_id,
            checkpoint_path=str(checkpoint_path),
        )

        mirror_checkpoint_to_legacy(checkpoint_path, checkpoint_id)
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
        target=_run_simulated_training,
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
