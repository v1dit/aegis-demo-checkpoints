from backend.app.env.simulator import simulate_episode


def test_simulation_events_are_deterministic_for_key() -> None:
    first = simulate_episode(
        seed=1003,
        scenario_id="scenario_unseen_web_rce",
        checkpoint_id="ckpt_blue_main_0009",
        defender_mode="ppo",
    )
    second = simulate_episode(
        seed=1003,
        scenario_id="scenario_unseen_web_rce",
        checkpoint_id="ckpt_blue_main_0009",
        defender_mode="ppo",
    )
    assert first.events == second.events
    assert first.metrics_series == second.metrics_series
