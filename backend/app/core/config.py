from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    project_name: str = "pantherhacks"
    api_port: int = 8000
    replay_dir: Path = Path("artifacts/replays")
    checkpoint_dir: Path = Path("artifacts/checkpoints")
    eval_report_dir: Path = Path("artifacts/eval_reports")
    use_rllib: bool = True
    ppo_lr: float = 0.0003
    ppo_gamma: float = 0.99
    ppo_train_batch_size: int = 4000
    ppo_num_rollout_workers: int = 0
    ppo_horizon: int = 200
    ppo_scenario_id: str = "scenario_unseen_web_rce"
    red_stochastic_probability: float = 0.3
    ppo_require_preflight_gate: bool = True
    ppo_heavy_timesteps_threshold: int = 100000
    ppo_preflight_iterations: int = 5
    ppo_preflight_min_entropy: float = 0.01

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
