from __future__ import annotations

from backend.app.rl.blue_policy import PPOBluePolicy, RLlibBluePolicy, policy_for


def test_policy_for_legacy_checkpoint_uses_heuristic_policy() -> None:
    policy = policy_for(
        mode="ppo",
        seed=41,
        checkpoint_payload={"checkpoint_id": "ckpt_old", "policy_bias": 0.88},
        horizon=200,
    )
    assert isinstance(policy, PPOBluePolicy)


def test_policy_for_rllib_checkpoint_uses_rllib_inference_policy() -> None:
    policy = policy_for(
        mode="ppo",
        seed=41,
        checkpoint_payload={
            "checkpoint_id": "ckpt_new",
            "trainer": "rllib_ppo",
            "rllib_checkpoint_path": "/tmp/mock-rllib-ckpt",
        },
        horizon=200,
    )
    assert isinstance(policy, RLlibBluePolicy)
