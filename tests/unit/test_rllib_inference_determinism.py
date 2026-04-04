from __future__ import annotations

from backend.app.rl.rllib_runner import compute_deterministic_action


class _FakeAlgo:
    def __init__(self) -> None:
        self.last_explore = None

    def compute_single_action(self, observation, *, explore):
        self.last_explore = explore
        return 3, {"logits": [0.1]}, {}


def test_compute_deterministic_action_disables_exploration() -> None:
    algo = _FakeAlgo()
    action = compute_deterministic_action(algo, [0.0, 0.1, 0.2])
    assert action == 3
    assert algo.last_explore is False
