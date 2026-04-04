from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Literal

from backend.app.rl.actions import BLUE_ACTIONS


@dataclass
class BlueDecision:
    action_type: str
    target_host: str
    target_service: str | None = None
    expected_effect: str = "reduce blast radius"


class BluePolicy:
    name = "blue"

    def decide(
        self,
        step: int,
        hosts: list[str],
        compromised_hosts: set[str],
        recent_red_target: str,
        services_by_host: dict[str, list[str]],
    ) -> BlueDecision | None:
        raise NotImplementedError


class NoDefensePolicy(BluePolicy):
    name = "none"

    def decide(
        self,
        step: int,
        hosts: list[str],
        compromised_hosts: set[str],
        recent_red_target: str,
        services_by_host: dict[str, list[str]],
    ) -> BlueDecision | None:
        return None


class RuleBasedBluePolicy(BluePolicy):
    name = "rule"

    def decide(
        self,
        step: int,
        hosts: list[str],
        compromised_hosts: set[str],
        recent_red_target: str,
        services_by_host: dict[str, list[str]],
    ) -> BlueDecision:
        if compromised_hosts:
            target = sorted(compromised_hosts)[0]
            return BlueDecision(
                action_type="isolate_host",
                target_host=target,
                expected_effect="contain lateral spread",
            )
        if step % 3 == 0:
            return BlueDecision(
                action_type="monitor_host",
                target_host=recent_red_target,
                expected_effect="increase detection probability",
            )
        target = hosts[step % len(hosts)]
        service = services_by_host[target][0]
        return BlueDecision(
            action_type="patch_service",
            target_host=target,
            target_service=service,
            expected_effect="remove exploit path",
        )


class PPOBluePolicy(BluePolicy):
    name = "ppo"

    def __init__(self, seed: int, checkpoint_bias: float = 0.82) -> None:
        self._rng = random.Random(seed)
        self._checkpoint_bias = checkpoint_bias

    def decide(
        self,
        step: int,
        hosts: list[str],
        compromised_hosts: set[str],
        recent_red_target: str,
        services_by_host: dict[str, list[str]],
    ) -> BlueDecision:
        if compromised_hosts:
            target = sorted(compromised_hosts)[0]
            return BlueDecision(
                action_type="isolate_host",
                target_host=target,
                expected_effect="contain lateral spread",
            )
        if step % 4 == 0:
            return BlueDecision(
                action_type="deploy_deception",
                target_host=recent_red_target,
                expected_effect="raise attacker uncertainty",
            )
        if step % 5 == 0:
            target = recent_red_target
            return BlueDecision(
                action_type="rotate_credentials",
                target_host=target,
                expected_effect="invalidate stolen credentials",
            )
        if self._rng.random() < self._checkpoint_bias:
            return BlueDecision(
                action_type="monitor_host",
                target_host=recent_red_target,
                expected_effect="reduce detection latency",
            )
        target = hosts[(step + 1) % len(hosts)]
        action = BLUE_ACTIONS[(step + 2) % len(BLUE_ACTIONS)]
        if action == "patch_service":
            return BlueDecision(
                action_type=action,
                target_host=target,
                target_service=services_by_host[target][0],
                expected_effect="remove exploit path",
            )
        return BlueDecision(action_type=action, target_host=target)


def policy_for(
    mode: Literal["none", "rule", "ppo"],
    seed: int,
    checkpoint_bias: float | None = None,
) -> BluePolicy:
    if mode == "none":
        return NoDefensePolicy()
    if mode == "rule":
        return RuleBasedBluePolicy()
    return PPOBluePolicy(seed=seed, checkpoint_bias=checkpoint_bias or 0.82)
