from __future__ import annotations

from backend.app.rl.red_policy import ScriptedRedPolicy

HOSTS = ["host_01", "host_02", "host_03"]
SERVICES = {host: ["web", "api"] for host in HOSTS}


def _actions(policy: ScriptedRedPolicy, steps: int = 24) -> list[str]:
    return [
        policy.decide(step=i, hosts=HOSTS, service_lookup=SERVICES).action_type
        for i in range(1, steps + 1)
    ]


def test_scripted_policy_is_deterministic_when_stochastic_probability_is_zero() -> None:
    first = _actions(ScriptedRedPolicy(seed=7, stochastic_branch_probability=0.0))
    second = _actions(ScriptedRedPolicy(seed=7, stochastic_branch_probability=0.0))
    assert first == second


def test_stochastic_policy_remains_seed_reproducible() -> None:
    first = _actions(ScriptedRedPolicy(seed=9, stochastic_branch_probability=0.3))
    second = _actions(ScriptedRedPolicy(seed=9, stochastic_branch_probability=0.3))
    assert first == second


def test_stochastic_policy_diverges_from_fully_scripted_pattern() -> None:
    scripted = _actions(ScriptedRedPolicy(seed=11, stochastic_branch_probability=0.0))
    stochastic = _actions(ScriptedRedPolicy(seed=11, stochastic_branch_probability=0.3))
    assert stochastic != scripted
