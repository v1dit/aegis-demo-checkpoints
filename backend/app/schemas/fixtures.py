from __future__ import annotations

from pathlib import Path

import orjson


def write_contract_fixtures(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)

    fixtures = {
        "action_event.json": {
            "event_id": "evt_000001",
            "ts_ms": 1712412345678,
            "step": 17,
            "actor": "RED",
            "action_type": "exploit_vulnerability",
            "source_host": "host_03",
            "target_host": "host_07",
            "target_service": "api",
            "outcome": "success",
            "mitre_tactic": "Initial Access",
            "confidence": 0.91,
        },
        "state_delta.json": {
            "ts_ms": 1712412345680,
            "step": 17,
            "node_changes": [
                {"node_id": "host_07", "compromise_state": "compromised", "defense_state": "none"}
            ],
            "edge_changes": [{"edge_id": "host_03->host_07", "status": "active"}],
        },
        "detection_event.json": {
            "event_id": "det_000034",
            "ts_ms": 1712412345692,
            "step": 18,
            "detector": "BLUE",
            "target_host": "host_07",
            "signal": "traffic_spike",
            "severity": "high",
            "detected": True,
        },
        "explainability_record.json": {
            "ts_ms": 1712412345695,
            "step": 18,
            "action": "isolate_host",
            "target_host": "host_07",
            "confidence": 0.82,
            "reason_features": [
                {"name": "traffic_spike_ratio", "value": 3.1},
                {"name": "lateral_movement_pattern_match", "value": 0.77},
                {"name": "critical_asset_risk", "value": 0.88},
            ],
            "expected_effect": "contain lateral spread",
        },
        "replay_manifest.json": {
            "replay_id": "replay_hero_01",
            "scenario_id": "scenario_unseen_web_rce",
            "seed": 1003,
            "checkpoint_id": "ckpt_blue_main_0009",
            "duration_steps": 200,
            "files": {
                "events": "events.jsonl",
                "topology": "topology_snapshots.json",
                "metrics": "metrics.json",
            },
        },
        "eval_report.json": {
            "eval_id": "eval_20260404_001",
            "suite_id": "heldout_suite_v1",
            "kpis": {
                "damage_reduction_vs_no_defense": 0.33,
                "damage_reduction_vs_rule_based": 0.19,
                "detection_latency_improvement_vs_rule_based": 0.24,
            },
            "per_scenario": [],
        },
    }

    for name, payload in fixtures.items():
        (root / name).write_bytes(
            orjson.dumps(
                payload,
                option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS,
            )
        )
