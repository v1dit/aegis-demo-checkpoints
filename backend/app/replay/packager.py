from __future__ import annotations

from pathlib import Path

import orjson

from backend.app.core.runs import (
    mirror_replays_to_legacy,
    read_checkpoint_payload,
    update_replay_manifest,
)
from backend.app.env.simulator import simulate_episode
from backend.app.replay.builder import build_replay_bundle
from backend.app.schemas.contracts import ReplayManifest

DEMO_REPLAY_PLAN = [
    ("replay_hero_01", "scenario_unseen_web_rce", 1003),
    ("replay_alt_02", "scenario_phishing_entry", 1001),
    ("replay_alt_03", "scenario_creds_chain", 1002),
    ("replay_alt_04", "scenario_data_zone_pivot", 1004),
    ("replay_enterprise_05", "scenario_enterprise_crm_identity_chain_v1", 2005),
]


def _checkpoint_payload(checkpoint_id: str, run_id: str | None) -> dict:
    return read_checkpoint_payload(checkpoint_id=checkpoint_id, run_id=run_id) or {}


def package_demo_replays(
    checkpoint_id: str,
    replay_root: Path,
    run_id: str | None = None,
) -> list[ReplayManifest]:
    replay_root.mkdir(parents=True, exist_ok=True)
    manifests: list[ReplayManifest] = []
    checkpoint_payload = _checkpoint_payload(checkpoint_id, run_id)
    checkpoint_bias = (
        float(checkpoint_payload["policy_bias"]) if "policy_bias" in checkpoint_payload else None
    )

    for replay_id, scenario_id, seed in DEMO_REPLAY_PLAN:
        simulation = simulate_episode(
            seed=seed,
            scenario_id=scenario_id,
            checkpoint_id=checkpoint_id,
            defender_mode="ppo",
            checkpoint_bias=checkpoint_bias,
            checkpoint_payload=checkpoint_payload,
            run_id=run_id,
        )
        manifests.append(
            build_replay_bundle(
                simulation,
                replay_id=replay_id,
                replay_root=replay_root,
            )
        )

    if run_id:
        update_replay_manifest(run_id, [manifest.replay_id for manifest in manifests], replay_root)
        mirror_replays_to_legacy(replay_root)

    return manifests


def write_ws_mock_frames(replay_root: Path, fixtures_root: Path) -> Path:
    fixtures_root.mkdir(parents=True, exist_ok=True)
    hero_events_path = replay_root / "replay_hero_01" / "events.jsonl"
    if not hero_events_path.exists():
        raise FileNotFoundError("Hero replay not found. Run package_demo_replays first.")

    lines = hero_events_path.read_bytes().splitlines()
    sample = [orjson.loads(line) for line in lines[:30]]
    output = fixtures_root / "replay_stream_sample.json"
    output.write_bytes(orjson.dumps(sample, option=orjson.OPT_INDENT_2))
    return output
