from backend.app.env.catalog import MITRE_TACTIC_BY_ACTION
from backend.app.explainability.reasoner import build_explainability_record
from backend.app.rl.reward import compute_blue_reward

REQUIRED_ACTIONS = {
    "scan_host",
    "enumerate_service",
    "exploit_vulnerability",
    "lateral_move",
    "privilege_escalate",
    "exfiltrate_data",
    "monitor_host",
    "patch_service",
    "isolate_host",
    "block_connection",
    "rotate_credentials",
    "deploy_deception",
}


def test_required_mitre_action_mapping_exists() -> None:
    for action in REQUIRED_ACTIONS:
        assert action in MITRE_TACTIC_BY_ACTION



def test_reward_penalizes_damage_and_rewards_detection() -> None:
    positive = compute_blue_reward(
        compromise_success=False,
        exfil_success=False,
        detection_success=True,
        containment_success=True,
        false_positive_cost=0.0,
        isolation_cost=0.0,
    )
    negative = compute_blue_reward(
        compromise_success=True,
        exfil_success=True,
        detection_success=False,
        containment_success=False,
        false_positive_cost=0.1,
        isolation_cost=0.1,
    )
    assert positive > 0
    assert negative < 0


def test_reward_is_clipped_to_normalized_range() -> None:
    highest = compute_blue_reward(
        compromise_success=False,
        exfil_success=False,
        detection_success=True,
        containment_success=True,
        false_positive_cost=0.0,
        isolation_cost=0.0,
        prevention_success=True,
        survival_bonus=0.05,
    )
    lowest = compute_blue_reward(
        compromise_success=True,
        exfil_success=True,
        detection_success=False,
        containment_success=False,
        false_positive_cost=1.0,
        isolation_cost=1.0,
        service_disruption_penalty=1.0,
        action_repeat_penalty=1.0,
    )
    assert -1.0 <= highest <= 1.0
    assert -1.0 <= lowest <= 1.0
    assert highest > 0
    assert lowest == -1.0


def test_reward_penalizes_repeated_action_farming() -> None:
    base = compute_blue_reward(
        compromise_success=False,
        exfil_success=False,
        detection_success=True,
        containment_success=False,
        false_positive_cost=0.0,
        isolation_cost=0.0,
    )
    repeated = compute_blue_reward(
        compromise_success=False,
        exfil_success=False,
        detection_success=True,
        containment_success=False,
        false_positive_cost=0.0,
        isolation_cost=0.0,
        action_repeat_penalty=0.1,
    )
    assert repeated < base



def test_explainability_record_is_deterministic() -> None:
    first = build_explainability_record(
        ts_ms=1712412345695,
        step=18,
        action="isolate_host",
        target_host="host_07",
        confidence=0.82,
        compromised_count=2,
        detections_count=3,
    )
    second = build_explainability_record(
        ts_ms=1712412345695,
        step=18,
        action="isolate_host",
        target_host="host_07",
        confidence=0.82,
        compromised_count=2,
        detections_count=3,
    )
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
