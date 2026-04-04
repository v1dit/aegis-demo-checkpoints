from __future__ import annotations

import threading

from backend.app.core.ids import prefixed_id
from backend.app.core.runs import (
    compute_improvement_delta,
    get_active_run_id,
    get_parent_kpis,
    mirror_eval_to_legacy,
    run_stage_dirs,
    update_eval_manifest,
)
from backend.app.core.state import shared_state
from backend.app.rl.eval import acceptance_gate_status, evaluate_checkpoint, write_eval_report
from backend.app.schemas.contracts import EvalReport, EvalRunRequest

_eval_counter = 0


def _next_eval_id() -> str:
    global _eval_counter
    _eval_counter += 1
    return prefixed_id("eval", _eval_counter)


def _run_eval(eval_id: str, request: EvalRunRequest, run_id: str) -> None:
    try:
        with shared_state.lock:
            shared_state.eval_runs[eval_id]["status"] = "running"

        run_dirs = run_stage_dirs(run_id)
        report = evaluate_checkpoint(
            eval_id=eval_id,
            checkpoint_id=request.checkpoint_id,
            suite_id=request.suite_id,
            seeds=request.seeds,
            replay_root=run_dirs["replays"],
            run_id=run_id,
        )
        output_path = write_eval_report(report, run_dirs["eval"])
        gates = acceptance_gate_status(report)

        mirror_eval_to_legacy(output_path)

        parent_kpis = get_parent_kpis(shared_state.train_runs.get(run_id, {}).get("parent_run_id"))
        delta = compute_improvement_delta(report.kpis.model_dump(mode="json"), parent_kpis)
        report.improvement_delta_vs_parent = delta

        update_eval_manifest(
            run_id,
            eval_id=eval_id,
            status="completed",
            report_path=str(output_path),
            kpis=report.kpis.model_dump(mode="json"),
            gates=gates,
            improvement_delta=delta,
        )

        with shared_state.lock:
            shared_state.eval_runs[eval_id].update(
                {
                    "status": "completed",
                    "run_id": run_id,
                    "report": report.model_dump(mode="json"),
                    "report_path": str(output_path),
                    "gates": gates,
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


def start_eval_job(request: EvalRunRequest, replay_dir, report_dir) -> tuple[str, str]:
    _ = replay_dir
    _ = report_dir

    eval_id = _next_eval_id()
    run_id = request.run_id or get_active_run_id() or prefixed_id("run", 0)
    with shared_state.lock:
        shared_state.eval_runs[eval_id] = {
            "eval_id": eval_id,
            "run_id": run_id,
            "status": "queued",
            "report": None,
            "request": request.model_dump(mode="json"),
            "report_path": None,
            "gates": None,
        }

    thread = threading.Thread(
        target=_run_eval,
        args=(eval_id, request, run_id),
        daemon=True,
        name=f"eval-{eval_id}",
    )
    thread.start()
    return eval_id, run_id


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
