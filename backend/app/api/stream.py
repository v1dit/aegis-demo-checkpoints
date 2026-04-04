from __future__ import annotations

import asyncio
import hashlib

import orjson
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.app.core.paths import REPLAY_DIR
from backend.app.core.runs import get_active_run_id, run_stage_dirs
from backend.app.env.simulator import simulate_episode

router = APIRouter(prefix="/stream", tags=["stream"])


def _seed_from_session(session_id: str) -> int:
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return (int(digest[:8], 16) % 9000) + 1000


@router.websocket("/live/{session_id}")
async def live_stream(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    seed = _seed_from_session(session_id)
    simulation = simulate_episode(
        seed=seed,
        scenario_id="scenario_live_burst",
        checkpoint_id="checkpoint_blue_demo_best",
        defender_mode="ppo",
        horizon=150,
    )

    try:
        sent = 0
        for event in simulation.events:
            await websocket.send_json({"event_type": "action", "payload": event})
            sent += 1
            if sent >= 120:
                break
            await asyncio.sleep(0.2)

        await websocket.send_json(
            {
                "event_type": "metric",
                "payload": {
                    "session_id": session_id,
                    "total_events": sent,
                    "sync_drift_budget_ms": 100,
                },
            }
        )
    except WebSocketDisconnect:
        return


@router.websocket("/replay/{replay_id}")
async def replay_stream(websocket: WebSocket, replay_id: str) -> None:
    await websocket.accept()
    run_id = get_active_run_id()
    if run_id:
        events_path = run_stage_dirs(run_id)["replays"] / replay_id / "events.jsonl"
        if not events_path.exists():
            events_path = REPLAY_DIR / replay_id / "events.jsonl"
    else:
        events_path = REPLAY_DIR / replay_id / "events.jsonl"

    if not events_path.exists():
        await websocket.send_json(
            {
                "event_type": "marker",
                "payload": {"error": "replay_not_found"},
            }
        )
        await websocket.close(code=1008)
        return

    try:
        for raw_line in events_path.read_bytes().splitlines():
            event = orjson.loads(raw_line)
            await websocket.send_json({"event_type": "action", "payload": event})
            await asyncio.sleep(0.02)
        await websocket.send_json({"event_type": "marker", "payload": {"status": "completed"}})
    except WebSocketDisconnect:
        return
