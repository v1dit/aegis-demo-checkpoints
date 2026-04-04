from __future__ import annotations

import random
from dataclasses import dataclass

from backend.app.rl.actions import RED_ACTIONS


@dataclass
class RedDecision:
    action_type: str
    source_host: str
    target_host: str
    target_service: str


class ScriptedRedPolicy:
    def __init__(self, seed: int, stochastic_branch_probability: float = 0.0) -> None:
        self._rng = random.Random(seed)
        self._stochastic_branch_probability = max(0.0, min(1.0, stochastic_branch_probability))

    def decide(
        self,
        step: int,
        hosts: list[str],
        service_lookup: dict[str, list[str]],
    ) -> RedDecision:
        scripted_action = RED_ACTIONS[(step - 1) % len(RED_ACTIONS)]
        action_type = scripted_action
        if self._stochastic_branch_probability > 0.0 and (
            self._rng.random() < self._stochastic_branch_probability
        ):
            action_type = self._rng.choice(RED_ACTIONS)
        source_host = hosts[(step - 1) % len(hosts)]
        if action_type == "lateral_move":
            target_host = hosts[(step + 3) % len(hosts)]
        else:
            target_host = hosts[(step + self._rng.randint(0, len(hosts) - 1)) % len(hosts)]
        service_list = service_lookup[target_host]
        target_service = service_list[(step - 1) % len(service_list)]
        return RedDecision(
            action_type=action_type,
            source_host=source_host,
            target_host=target_host,
            target_service=target_service,
        )
