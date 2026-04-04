from __future__ import annotations

from pathlib import Path
from typing import Any

import orjson

from backend.app.env.simulator import SimulationResult
from backend.app.schemas.contracts import ReplayFiles, ReplayListItem, ReplayManifest


def _write_json(path: Path, payload: Any) -> None:
    path.write_bytes(orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS))


def compute_sync_drift_ms(sim_result: SimulationResult) -> float:
    max_drift = 0.0
    metrics_by_step = {row["step"]: row["ts_ms"] for row in sim_result.metrics_series}
    deltas_by_step = {delta.step: delta.ts_ms for delta in sim_result.state_deltas}

    for event in sim_result.events:
        step = event.get("step")
        if step is None:
            continue
        metric_ts = metrics_by_step.get(step, event["ts_ms"])
        delta_ts = deltas_by_step.get(step, event["ts_ms"])
        drift = max(abs(event["ts_ms"] - metric_ts), abs(event["ts_ms"] - delta_ts))
        max_drift = max(max_drift, float(drift))

    return round(max_drift, 2)


def build_replay_bundle(
    sim_result: SimulationResult,
    replay_id: str,
    replay_root: Path,
) -> ReplayManifest:
    bundle_dir = replay_root / replay_id
    bundle_dir.mkdir(parents=True, exist_ok=True)

    events_path = bundle_dir / "events.jsonl"
    topology_path = bundle_dir / "topology_snapshots.json"
    metrics_path = bundle_dir / "metrics.json"
    manifest_path = bundle_dir / "manifest.json"

    events_lines = [orjson.dumps(event) for event in sim_result.events]
    events_path.write_bytes(b"\n".join(events_lines) + b"\n")

    topology_payload = {
        "initial": sim_result.topology.model_dump(mode="json"),
        "deltas": [delta.model_dump(mode="json") for delta in sim_result.state_deltas],
    }
    _write_json(topology_path, topology_payload)

    metrics_payload = {
        "timeseries": sim_result.metrics_series,
        "summary": {
            "damage": sim_result.summary.damage,
            "mean_detection_latency_ms": sim_result.summary.mean_detection_latency_ms,
            "attack_success_rate": sim_result.summary.attack_success_rate,
            "rewards_sum": sim_result.summary.rewards_sum,
            "exfiltration_count": sim_result.summary.exfiltration_count,
            "exfiltration_attempts": sim_result.summary.exfiltration_attempts,
            "critical_asset_compromise_rate": sim_result.summary.critical_asset_compromise_rate,
            "sync_drift_ms": compute_sync_drift_ms(sim_result),
        },
        "explainability": [record.model_dump(mode="json") for record in sim_result.explainability],
    }
    _write_json(metrics_path, metrics_payload)

    manifest = ReplayManifest(
        replay_id=replay_id,
        scenario_id=sim_result.scenario_id,
        seed=sim_result.seed,
        checkpoint_id=sim_result.checkpoint_id,
        duration_steps=len(sim_result.metrics_series),
        files=ReplayFiles(
            events="events.jsonl",
            topology="topology_snapshots.json",
            metrics="metrics.json",
        ),
    )
    _write_json(manifest_path, manifest.model_dump(mode="json"))
    return manifest


def list_replay_manifests(replay_root: Path) -> list[ReplayListItem]:
    if not replay_root.exists():
        return []

    items: list[ReplayListItem] = []
    for directory in sorted(replay_root.iterdir()):
        manifest_path = directory / "manifest.json"
        if not manifest_path.exists() or not directory.is_dir():
            continue
        payload = orjson.loads(manifest_path.read_bytes())
        manifest = ReplayManifest.model_validate(payload)
        items.append(
            ReplayListItem(
                replay_id=manifest.replay_id,
                scenario_id=manifest.scenario_id,
                checkpoint_id=manifest.checkpoint_id,
                seed=manifest.seed,
            )
        )
    return items


def load_replay_bundle(replay_root: Path, replay_id: str) -> dict[str, Any]:
    bundle_dir = replay_root / replay_id
    manifest_path = bundle_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Replay {replay_id} not found")

    manifest = ReplayManifest.model_validate(orjson.loads(manifest_path.read_bytes()))
    return {
        "replay_id": replay_id,
        "bundle_dir": str(bundle_dir),
        "manifest": manifest,
        "files": {
            "events": str(bundle_dir / manifest.files.events),
            "topology": str(bundle_dir / manifest.files.topology),
            "metrics": str(bundle_dir / manifest.files.metrics),
            "manifest": str(manifest_path),
        },
    }
