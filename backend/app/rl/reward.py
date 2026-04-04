from __future__ import annotations


def compute_blue_reward(
    compromise_success: bool,
    exfil_success: bool,
    detection_success: bool,
    containment_success: bool,
    false_positive_cost: float,
    isolation_cost: float,
    prevention_success: bool = False,
    survival_bonus: float = 0.0,
    service_disruption_penalty: float = 0.0,
    action_repeat_penalty: float = 0.0,
) -> float:
    reward = 0.0
    if detection_success:
        reward += 0.20
    if prevention_success:
        reward += 0.30
    if containment_success:
        reward += 0.40
    reward += max(0.0, survival_bonus)
    if compromise_success:
        reward -= 0.50
    if exfil_success:
        reward -= 1.00

    disruption_penalty = (
        max(0.0, false_positive_cost)
        + max(0.0, isolation_cost)
        + max(0.0, service_disruption_penalty)
    )
    reward -= disruption_penalty
    reward -= max(0.0, action_repeat_penalty)
    return max(-1.0, min(1.0, reward))
