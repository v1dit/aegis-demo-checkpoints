from __future__ import annotations

import random

from backend.app.schemas.contracts import ExplainabilityRecord, FeatureValue


def build_explainability_record(
    ts_ms: int,
    step: int,
    action: str,
    target_host: str,
    confidence: float,
    compromised_count: int,
    detections_count: int,
) -> ExplainabilityRecord:
    rng = random.Random((step * 1009) + len(target_host))
    traffic_spike_ratio = round(1.1 + (compromised_count * 0.4) + rng.random(), 2)
    lateral_match = round(min(0.99, 0.2 + (compromised_count * 0.15) + rng.random() * 0.3), 2)
    critical_asset_risk = round(min(0.99, 0.3 + (detections_count * 0.08) + rng.random() * 0.25), 2)
    return ExplainabilityRecord(
        ts_ms=ts_ms,
        step=step,
        action=action,
        target_host=target_host,
        confidence=round(confidence, 2),
        reason_features=[
            FeatureValue(name="traffic_spike_ratio", value=traffic_spike_ratio),
            FeatureValue(name="lateral_movement_pattern_match", value=lateral_match),
            FeatureValue(name="critical_asset_risk", value=critical_asset_risk),
        ],
        expected_effect="contain lateral spread",
    )
