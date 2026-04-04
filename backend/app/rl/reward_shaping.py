from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_SURVIVAL_BONUS = 0.05
DEFAULT_REPEAT_WINDOW = 3
DEFAULT_REPEAT_PENALTY = 0.10


def prevention_success_for_transition(
    *,
    action_type: str,
    was_compromised: bool,
    previous_defense_state: str,
    new_defense_state: str,
    meaningful_state_change: bool,
) -> bool:
    if was_compromised or not meaningful_state_change:
        return False
    if action_type not in {"patch_service", "monitor_host"}:
        return False
    if previous_defense_state in {"hardened", "monitored"}:
        return False
    return new_defense_state in {"hardened", "monitored"}


def survival_bonus_for_step(
    *,
    exfil_success: bool,
    new_compromise: bool,
    bonus: float = DEFAULT_SURVIVAL_BONUS,
) -> float:
    if exfil_success or new_compromise:
        return 0.0
    return bonus


@dataclass
class ActionRepeatTracker:
    window: int = DEFAULT_REPEAT_WINDOW
    penalty: float = DEFAULT_REPEAT_PENALTY
    _last_action_step: dict[tuple[str, str], int] = field(default_factory=dict)

    def penalty_for(
        self,
        action_type: str,
        target_host: str,
        *,
        step: int,
        meaningful_state_change: bool,
    ) -> float:
        key = (action_type, target_host)
        previous_step = self._last_action_step.get(key)
        self._last_action_step[key] = step
        if previous_step is None:
            return 0.0
        if step - previous_step > self.window:
            return 0.0
        if meaningful_state_change:
            return 0.0
        return self.penalty


def repeat_penalty_probe_events() -> int:
    tracker = ActionRepeatTracker()
    events = 0
    sequence = [
        ("patch_service", "host_01", 1, True),
        ("patch_service", "host_01", 2, False),
        ("patch_service", "host_01", 3, False),
        ("patch_service", "host_01", 7, False),
    ]
    for action_type, target_host, step, meaningful_state_change in sequence:
        penalty = tracker.penalty_for(
            action_type=action_type,
            target_host=target_host,
            step=step,
            meaningful_state_change=meaningful_state_change,
        )
        if penalty > 0:
            events += 1
    return events
