from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app.core.runs import get_active_run_id, list_run_ids, load_manifest, run_stage_dirs
from backend.app.replay.builder import list_replay_manifests, load_replay_bundle
from backend.app.schemas.contracts import (
    ReplayBundleResponse,
    ReplayListResponse,
    RunListItem,
    RunListResponse,
)

router = APIRouter(prefix="/replay", tags=["replay"])


def _run_replay_root(run_id: str):
    try:
        load_manifest(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown run_id: {run_id}") from exc
    return run_stage_dirs(run_id)["replays"]


@router.get("/list", response_model=ReplayListResponse)
def replay_list() -> ReplayListResponse:
    run_id = get_active_run_id()
    if not run_id:
        return ReplayListResponse(run_id=None, replays=[])
    replay_root = run_stage_dirs(run_id)["replays"]
    return ReplayListResponse(run_id=run_id, replays=list_replay_manifests(replay_root))


@router.get("/runs", response_model=RunListResponse)
def replay_runs() -> RunListResponse:
    runs: list[RunListItem] = []
    for run_id in reversed(list_run_ids()):
        manifest = load_manifest(run_id)
        replays = manifest.get("replays", {})
        replay_ids = replays.get("replay_ids", [])
        runs.append(
            RunListItem(
                run_id=run_id,
                created_at=manifest.get("created_at"),
                updated_at=manifest.get("updated_at"),
                train_status=manifest.get("train", {}).get("status", "unknown"),
                eval_status=manifest.get("eval", {}).get("status", "unknown"),
                replay_status=replays.get("status", "unknown"),
                replay_count=len(replay_ids) if isinstance(replay_ids, list) else 0,
            )
        )
    return RunListResponse(runs=runs)


@router.get("/runs/{run_id}/list", response_model=ReplayListResponse)
def replay_list_for_run(run_id: str) -> ReplayListResponse:
    replay_root = _run_replay_root(run_id)
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


@router.get("/runs/{run_id}/{replay_id}/bundle", response_model=ReplayBundleResponse)
def replay_bundle_for_run(run_id: str, replay_id: str) -> ReplayBundleResponse:
    replay_root = _run_replay_root(run_id)
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
