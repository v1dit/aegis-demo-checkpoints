from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Literal

from backend.app.rl.actions import BLUE_ACTIONS
from backend.app.rl.policy_features import (
    action_type_for_index,
    build_policy_observation,
    target_for_action,
)
from backend.app.rl.rllib_runner import (
    RLlibUnavailableError,
    compute_deterministic_action,
    restore_algorithm_from_checkpoint,
)


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


class RLlibBluePolicy(BluePolicy):
    name = "ppo_rllib"

    def __init__(self, checkpoint_path: str, horizon: int = 200) -> None:
        self._checkpoint_path = checkpoint_path
        self._horizon = horizon
        self._algo: Any | None = None

    def _algorithm(self) -> Any:
        if self._algo is None:
            self._algo = restore_algorithm_from_checkpoint(self._checkpoint_path)
        return self._algo

    def decide(
        self,
        step: int,
        hosts: list[str],
        compromised_hosts: set[str],
        recent_red_target: str,
        services_by_host: dict[str, list[str]],
    ) -> BlueDecision:
        observation = build_policy_observation(
            step=step,
            horizon=self._horizon,
            hosts=hosts,
            compromised_hosts=compromised_hosts,
            recent_red_target=recent_red_target,
        )
        try:
            action_index = compute_deterministic_action(self._algorithm(), observation)
        except RLlibUnavailableError as exc:
            raise RuntimeError("RLlib checkpoint requires ray[rllib] for inference") from exc

        action_type = action_type_for_index(action_index)
        target = target_for_action(
            action_type=action_type,
            hosts=hosts,
            compromised_hosts=compromised_hosts,
            recent_red_target=recent_red_target,
        )
        if action_type == "patch_service":
            return BlueDecision(
                action_type=action_type,
                target_host=target,
                target_service=services_by_host[target][0],
                expected_effect="remove exploit path",
            )
        expected_effect = {
            "monitor_host": "reduce detection latency",
            "isolate_host": "contain lateral spread",
            "block_connection": "disrupt attacker movement",
            "rotate_credentials": "invalidate stolen credentials",
            "deploy_deception": "raise attacker uncertainty",
        }.get(action_type, "reduce blast radius")
        return BlueDecision(
            action_type=action_type,
            target_host=target,
            expected_effect=expected_effect,
        )


def policy_for(
    mode: Literal["none", "rule", "ppo"],
    seed: int,
    checkpoint_bias: float | None = None,
    checkpoint_payload: dict[str, Any] | None = None,
    horizon: int = 200,
) -> BluePolicy:
    if mode == "none":
        return NoDefensePolicy()
    if mode == "rule":
        return RuleBasedBluePolicy()

    payload = checkpoint_payload or {}
    trainer = str(payload.get("trainer", ""))
    rllib_checkpoint_path = payload.get("rllib_checkpoint_path")
    if trainer == "rllib_ppo" and isinstance(rllib_checkpoint_path, str) and rllib_checkpoint_path:
        return RLlibBluePolicy(checkpoint_path=rllib_checkpoint_path, horizon=horizon)

    legacy_bias = checkpoint_bias
    if legacy_bias is None and "policy_bias" in payload:
        legacy_bias = float(payload["policy_bias"])
    return PPOBluePolicy(seed=seed, checkpoint_bias=legacy_bias or 0.82)
