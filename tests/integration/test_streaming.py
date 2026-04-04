from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.replay.packager import package_demo_replays


def test_replay_stream_websocket(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.app.replay.packager.read_checkpoint_payload",
        lambda checkpoint_id, run_id=None: {"policy_bias": 0.82},
    )
    monkeypatch.setattr("backend.app.core.runs.get_active_run_id", lambda: None)
    monkeypatch.setattr("backend.app.api.stream.REPLAY_DIR", tmp_path / "artifacts/replays")

    package_demo_replays(
        checkpoint_id="checkpoint_blue_demo_best",
        replay_root=tmp_path / "artifacts/replays",
    )

    client = TestClient(app)
    with client.websocket_connect("/stream/replay/replay_hero_01") as ws:
        message = ws.receive_json()
        assert message["event_type"] == "action"
        assert "payload" in message


def test_live_stream_websocket(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.app.env.simulator.read_checkpoint_payload",
        lambda checkpoint_id, run_id=None: {"policy_bias": 0.82},
    )
    client = TestClient(app)
    with client.websocket_connect("/stream/live/session_test") as ws:
        message = ws.receive_json()
        assert message["event_type"] == "action"
        assert "payload" in message
