from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app.core.runs import get_active_run_id, run_stage_dirs
from backend.app.replay.builder import list_replay_manifests, load_replay_bundle
from backend.app.schemas.contracts import ReplayBundleResponse, ReplayListResponse

router = APIRouter(prefix="/replay", tags=["replay"])


@router.get("/list", response_model=ReplayListResponse)
def replay_list() -> ReplayListResponse:
    run_id = get_active_run_id()
    if not run_id:
        return ReplayListResponse(run_id=None, replays=[])
    replay_root = run_stage_dirs(run_id)["replays"]
    return ReplayListResponse(run_id=run_id, replays=list_replay_manifests(replay_root))


@router.get("/{replay_id}/bundle", response_model=ReplayBundleResponse)
def replay_bundle(replay_id: str) -> ReplayBundleResponse:
    run_id = get_active_run_id()
    if not run_id:
        raise HTTPException(status_code=404, detail="No active run")
    replay_root = run_stage_dirs(run_id)["replays"]
    try:
        payload = load_replay_bundle(replay_root, replay_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return ReplayBundleResponse(
        run_id=run_id,
        replay_id=payload["replay_id"],
        bundle_dir=payload["bundle_dir"],
        manifest=payload["manifest"],
        files=payload["files"],
    )
