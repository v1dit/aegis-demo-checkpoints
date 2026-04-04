from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.replay.packager import package_demo_replays


def test_replay_stream_websocket() -> None:
    package_demo_replays(
        checkpoint_id="checkpoint_blue_demo_best",
        replay_root=Path("artifacts/replays"),
    )

    client = TestClient(app)
    with client.websocket_connect("/stream/replay/replay_hero_01") as ws:
        message = ws.receive_json()
        assert message["event_type"] == "action"
        assert "payload" in message


def test_live_stream_websocket() -> None:
    client = TestClient(app)
    with client.websocket_connect("/stream/live/session_test") as ws:
        message = ws.receive_json()
        assert message["event_type"] == "action"
        assert "payload" in message
