from __future__ import annotations

from backend.app.rl.actions import BLUE_ACTIONS

OBSERVATION_DIM = 6


def build_policy_observation(
    *,
    step: int,
    horizon: int,
    hosts: list[str],
    compromised_hosts: set[str],
    recent_red_target: str,
) -> list[float]:
    host_count = max(1, len(hosts))
    horizon_count = max(1, horizon)
    target_index = hosts.index(recent_red_target) if recent_red_target in hosts else 0
    compromised_count = len(compromised_hosts)

    return [
        min(1.0, step / float(horizon_count)),
        min(1.0, compromised_count / float(host_count)),
        min(1.0, target_index / float(max(1, host_count - 1))),
        1.0 if recent_red_target in compromised_hosts else 0.0,
        min(1.0, compromised_count / 5.0),
        min(1.0, host_count / 20.0),
    ]


def clamp_action_index(action_index: int) -> int:
    return max(0, min(len(BLUE_ACTIONS) - 1, int(action_index)))


def action_type_for_index(action_index: int) -> str:
    return BLUE_ACTIONS[clamp_action_index(action_index)]


def target_for_action(
    *,
    action_type: str,
    hosts: list[str],
    compromised_hosts: set[str],
    recent_red_target: str,
) -> str:
    if action_type == "isolate_host" and compromised_hosts:
        return sorted(compromised_hosts)[0]
    if recent_red_target in hosts:
        return recent_red_target
    return hosts[0]
