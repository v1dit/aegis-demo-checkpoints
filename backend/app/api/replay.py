from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app.core.paths import REPLAY_DIR
from backend.app.replay.builder import list_replay_manifests, load_replay_bundle
from backend.app.schemas.contracts import ReplayBundleResponse, ReplayListResponse

router = APIRouter(prefix="/replay", tags=["replay"])


@router.get("/list", response_model=ReplayListResponse)
def replay_list() -> ReplayListResponse:
    return ReplayListResponse(replays=list_replay_manifests(REPLAY_DIR))


@router.get("/{replay_id}/bundle", response_model=ReplayBundleResponse)
def replay_bundle(replay_id: str) -> ReplayBundleResponse:
    try:
        payload = load_replay_bundle(REPLAY_DIR, replay_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return ReplayBundleResponse(
        replay_id=payload["replay_id"],
        bundle_dir=payload["bundle_dir"],
        manifest=payload["manifest"],
        files=payload["files"],
    )
