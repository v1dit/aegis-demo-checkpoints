from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app.core.paths import EVAL_REPORT_DIR, REPLAY_DIR
from backend.app.rl.eval_jobs import get_eval_report, get_eval_status, start_eval_job
from backend.app.schemas.contracts import EvalReport, EvalRunRequest, EvalRunResponse

router = APIRouter(prefix="/eval", tags=["eval"])


@router.post("/run", response_model=EvalRunResponse)
def run_eval(request: EvalRunRequest) -> EvalRunResponse:
    eval_id = start_eval_job(request=request, replay_dir=REPLAY_DIR, report_dir=EVAL_REPORT_DIR)
    return EvalRunResponse(eval_id=eval_id, status="started")


@router.get("/report/{eval_id}", response_model=EvalReport)
def eval_report(eval_id: str) -> EvalReport:
    try:
        status = get_eval_status(eval_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown eval_id: {eval_id}") from exc

    if status["status"] != "completed":
        raise HTTPException(status_code=409, detail={"status": status["status"]})

    try:
        return get_eval_report(eval_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail={"status": str(exc)}) from exc
