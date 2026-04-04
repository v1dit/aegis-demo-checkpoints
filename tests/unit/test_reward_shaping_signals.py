from __future__ import annotations

from backend.app.rl.reward_shaping import (
    ActionRepeatTracker,
    prevention_success_for_transition,
    survival_bonus_for_step,
)


def test_prevention_success_requires_hardening_before_compromise() -> None:
    assert prevention_success_for_transition(
        action_type="patch_service",
        was_compromised=False,
        previous_defense_state="none",
        new_defense_state="hardened",
        meaningful_state_change=True,
    )
    assert not prevention_success_for_transition(
        action_type="patch_service",
        was_compromised=True,
        previous_defense_state="none",
        new_defense_state="hardened",
        meaningful_state_change=True,
    )


def test_survival_bonus_requires_no_exfiltration_and_no_new_compromise() -> None:
    assert survival_bonus_for_step(exfil_success=False, new_compromise=False) == 0.05
    assert survival_bonus_for_step(exfil_success=True, new_compromise=False) == 0.0
    assert survival_bonus_for_step(exfil_success=False, new_compromise=True) == 0.0


def test_action_repeat_tracker_penalizes_recent_repetition_without_state_change() -> None:
    tracker = ActionRepeatTracker(window=3, penalty=0.1)
    assert (
        tracker.penalty_for("patch_service", "host_01", step=1, meaningful_state_change=True) == 0.0
    )
    assert (
        tracker.penalty_for("patch_service", "host_01", step=2, meaningful_state_change=False)
        == 0.1
    )
    assert (
        tracker.penalty_for("patch_service", "host_01", step=6, meaningful_state_change=False)
        == 0.0
    )
