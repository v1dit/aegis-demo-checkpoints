from __future__ import annotations

import threading
from pathlib import Path

from backend.app.core.ids import prefixed_id
from backend.app.core.state import shared_state
from backend.app.rl.eval import acceptance_gate_status, evaluate_checkpoint, write_eval_report
from backend.app.schemas.contracts import EvalReport, EvalRunRequest

_eval_counter = 0


def _next_eval_id() -> str:
    global _eval_counter
    _eval_counter += 1
    return prefixed_id("eval", _eval_counter)


def _run_eval(eval_id: str, request: EvalRunRequest, replay_dir: Path, report_dir: Path) -> None:
    try:
        with shared_state.lock:
            shared_state.eval_runs[eval_id]["status"] = "running"

        report = evaluate_checkpoint(
            eval_id=eval_id,
            checkpoint_id=request.checkpoint_id,
            suite_id=request.suite_id,
            seeds=request.seeds,
            replay_root=replay_dir,
        )
        output_path = write_eval_report(report, report_dir)

        with shared_state.lock:
            shared_state.eval_runs[eval_id].update(
                {
                    "status": "completed",
                    "report": report.model_dump(mode="json"),
                    "report_path": str(output_path),
                    "gates": acceptance_gate_status(report),
                }
            )
    except Exception as exc:  # pragma: no cover - defensive
        with shared_state.lock:
            shared_state.eval_runs[eval_id].update(
                {
                    "status": "failed",
                    "error": str(exc),
                }
            )


def start_eval_job(request: EvalRunRequest, replay_dir: Path, report_dir: Path) -> str:
    eval_id = _next_eval_id()
    with shared_state.lock:
        shared_state.eval_runs[eval_id] = {
            "eval_id": eval_id,
            "status": "queued",
            "report": None,
            "request": request.model_dump(mode="json"),
            "report_path": None,
            "gates": None,
        }

    thread = threading.Thread(
        target=_run_eval,
        args=(eval_id, request, replay_dir, report_dir),
        daemon=True,
        name=f"eval-{eval_id}",
    )
    thread.start()
    return eval_id


def get_eval_report(eval_id: str) -> EvalReport:
    with shared_state.lock:
        run = shared_state.eval_runs.get(eval_id)
    if run is None:
        raise KeyError(eval_id)
    if run.get("status") != "completed":
        raise RuntimeError(run.get("status", "unknown"))
    return EvalReport.model_validate(run["report"])


def get_eval_status(eval_id: str) -> dict:
    with shared_state.lock:
        run = shared_state.eval_runs.get(eval_id)
    if run is None:
        raise KeyError(eval_id)
    return run
