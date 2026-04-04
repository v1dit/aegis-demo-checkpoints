from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    project_name: str = "pantherhacks"
    api_port: int = 8000
    replay_dir: Path = Path("artifacts/replays")
    checkpoint_dir: Path = Path("artifacts/checkpoints")
    eval_report_dir: Path = Path("artifacts/eval_reports")
    use_rllib: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
