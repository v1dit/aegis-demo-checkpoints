from __future__ import annotations

import importlib.util
from typing import Any


class RLlibUnavailableError(RuntimeError):
    pass


def rllib_available() -> bool:
    return importlib.util.find_spec("ray") is not None


def run_ppo_training(config: dict[str, Any]) -> dict[str, Any]:
    if not rllib_available():
        raise RLlibUnavailableError("ray[rllib] is not installed; use simulated trainer path")

    # This function is intentionally thin because DGX jobs in this repo default to
    # deterministic simulated training for weekend reliability. If RLlib is installed,
    # this returns a schema-compatible snapshot for downstream APIs.
    return {
        "trainer": "rllib_ppo",
        "status": "stubbed",
        "config": config,
    }
