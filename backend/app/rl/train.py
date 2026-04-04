from __future__ import annotations

import json
import random
import threading
import time
from pathlib import Path

from backend.app.core.ids import prefixed_id
from backend.app.core.state import shared_state
from backend.app.schemas.contracts import TrainRunRequest, TrainStatusResponse

_train_counter = 0


def _next_run_id() -> str:
    global _train_counter
    _train_counter += 1
    return prefixed_id("train", _train_counter)


def _checkpoint_id_for_run(run_id: str) -> str:
    return f"ckpt_blue_main_{run_id.split('_')[-1]}"


def _run_simulated_training(run_id: str, request: TrainRunRequest, checkpoint_dir: Path) -> None:
    rng = random.Random(request.seed)
    try:
        with shared_state.lock:
            shared_state.train_runs[run_id]["status"] = "running"
            shared_state.train_runs[run_id]["phase"] = "warmup"

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
                with shared_state.lock:
                    shared_state.train_runs[run_id].update(
                        {
                            "phase": phase,
                            "timesteps": timesteps,
                            "learning_metrics": {
                                "blue_pressure_score": round(pressure, 4),
                                "attack_success_rate": round(attack_rate, 4),
                                "detection_latency_ms": round(latency, 2),
                            },
                        }
                    )
                time.sleep(0.08)

        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        checkpoint_id = _checkpoint_id_for_run(run_id)
        checkpoint_path = checkpoint_dir / f"{checkpoint_id}.json"
        checkpoint_payload = {
            "checkpoint_id": checkpoint_id,
            "run_id": run_id,
            "seed": request.seed,
            "policy_bias": round(0.78 + rng.random() * 0.12, 4),
            "config_profile": request.config_profile,
            "gpu_ids": request.gpu_ids,
            "timesteps": max_steps,
        }
        checkpoint_path.write_text(json.dumps(checkpoint_payload, indent=2), encoding="utf-8")
        demo_best_path = checkpoint_dir / "checkpoint_blue_demo_best.json"
        demo_best_path.write_text(json.dumps(checkpoint_payload, indent=2), encoding="utf-8")

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
    except Exception as exc:  # pragma: no cover - defensive
        with shared_state.lock:
            shared_state.train_runs[run_id].update(
                {
                    "status": "failed",
                    "phase": "failed",
                    "error": str(exc),
                }
            )


def start_training_job(request: TrainRunRequest, checkpoint_dir: Path) -> str:
    run_id = _next_run_id()
    with shared_state.lock:
        shared_state.train_runs[run_id] = {
            "run_id": run_id,
            "status": "queued",
            "phase": "queued",
            "timesteps": 0,
            "checkpoint_path": None,
            "learning_metrics": {},
            "request": request.model_dump(mode="json"),
        }

    thread = threading.Thread(
        target=_run_simulated_training,
        args=(run_id, request, checkpoint_dir),
        daemon=True,
        name=f"train-{run_id}",
    )
    thread.start()
    return run_id


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
        checkpoint_path=run.get("checkpoint_path"),
        learning_metrics=run.get("learning_metrics", {}),
    )
