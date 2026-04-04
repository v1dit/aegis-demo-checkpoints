from __future__ import annotations


def compute_blue_reward(
    compromise_success: bool,
    exfil_success: bool,
    detection_success: bool,
    containment_success: bool,
    false_positive_cost: float,
    isolation_cost: float,
) -> float:
    reward = 0.0
    if detection_success:
        reward += 2.0
    if containment_success:
        reward += 3.0
    if compromise_success:
        reward -= 4.0
    if exfil_success:
        reward -= 6.0
    reward -= false_positive_cost
    reward -= isolation_cost
    return reward
