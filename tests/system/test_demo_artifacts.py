from pathlib import Path

import orjson

from backend.app.cli import _package_replays
from backend.app.replay.builder import load_replay_bundle


def test_demo_artifacts_and_sync_budget() -> None:
    _package_replays()

    replay_root = Path("artifacts/replays")
    for replay_id in [
        "replay_hero_01",
        "replay_alt_02",
        "replay_alt_03",
        "replay_alt_04",
        "replay_enterprise_05",
    ]:
        bundle = load_replay_bundle(replay_root, replay_id)
        metrics_payload = orjson.loads(Path(bundle["files"]["metrics"]).read_bytes())
        assert metrics_payload["summary"]["sync_drift_ms"] <= 100
