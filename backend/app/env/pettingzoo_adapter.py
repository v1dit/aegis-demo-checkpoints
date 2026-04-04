from __future__ import annotations

from dataclasses import dataclass

from backend.app.env.simulator import simulate_episode


@dataclass
class PettingZooAdapterConfig:
    scenario_id: str = "scenario_unseen_web_rce"
    horizon: int = 200


class CyberRangeParallelEnv:
    """Minimal adapter surface for future RLlib/PettingZoo wiring."""

    def __init__(self, config: PettingZooAdapterConfig | None = None) -> None:
        self.config = config or PettingZooAdapterConfig()

    def rollout(self, seed: int, checkpoint_id: str, defender_mode: str) -> dict:
        result = simulate_episode(
            seed=seed,
            scenario_id=self.config.scenario_id,
            checkpoint_id=checkpoint_id,
            defender_mode=defender_mode,
            horizon=self.config.horizon,
        )
        return {
            "events": result.events,
            "metrics": result.metrics_series,
            "summary": result.summary,
        }
