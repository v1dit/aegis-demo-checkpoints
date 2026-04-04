from __future__ import annotations

from backend.app.rl.rllib_runner import (
    compute_deterministic_action,
    extract_policy_entropy,
    preflight_gate_status,
)


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


def test_extract_policy_entropy_reads_nested_learner_stats() -> None:
    result = {
        "info": {
            "learner": {
                "default_policy": {
                    "learner_stats": {
                        "entropy": 0.42,
                    }
                }
            }
        }
    }
    assert extract_policy_entropy(result) == 0.42


def test_preflight_gate_fails_for_entropy_collapse() -> None:
    status = preflight_gate_status(
        {
            "learning_metrics": {
                "episode_reward_mean": 0.11,
                "timesteps_total": 1000,
                "policy_entropy": 0.00001,
            },
            "reward_shaping_probe_repeat_penalties": 1,
        },
        min_entropy=0.01,
    )
    assert status.passed is False
    assert status.errors


def test_preflight_gate_passes_with_entropy_and_repeat_probe() -> None:
    status = preflight_gate_status(
        {
            "learning_metrics": {
                "episode_reward_mean": 0.15,
                "timesteps_total": 1000,
                "policy_entropy": 0.12,
            },
            "reward_shaping_probe_repeat_penalties": 2,
        },
        min_entropy=0.01,
    )
    assert status.passed is True
    assert status.errors == []
