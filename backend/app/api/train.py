from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app.core.paths import CHECKPOINT_DIR
from backend.app.rl.train import get_train_status, start_training_job
from backend.app.schemas.contracts import TrainRunRequest, TrainRunResponse, TrainStatusResponse

router = APIRouter(prefix="/train", tags=["train"])


@router.post("/run", response_model=TrainRunResponse)
def run_training(request: TrainRunRequest) -> TrainRunResponse:
    run_id, parent_info = start_training_job(request=request, checkpoint_dir=CHECKPOINT_DIR)
    return TrainRunResponse(
        run_id=run_id,
        status="started",
        parent_run_id=parent_info.parent_run_id,
        parent_checkpoint=parent_info.parent_checkpoint,
    )


@router.get("/status/{run_id}", response_model=TrainStatusResponse)
def train_status(run_id: str) -> TrainStatusResponse:
    try:
        return get_train_status(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown run_id: {run_id}") from exc
