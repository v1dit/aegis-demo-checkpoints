from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable, Protocol

from backend.app.env.simulator import SimulationResult, simulate_episode
from backend.app.schemas.topology import TopologySnapshot


class SandboxLauncher(Protocol):
    def run_episode(
        self,
        *,
        seed: int,
        horizon: int,
        checkpoint_id: str,
        topology: TopologySnapshot,
        red_target_priority: list[str],
        event_callback: Callable[[str, dict[str, Any]], None] | None,
        should_stop: Callable[[], bool] | None,
        step_delay_s: float,
    ) -> SimulationResult:
        ...


class LocalThreadLauncher:
    def run_episode(
        self,
        *,
        seed: int,
        horizon: int,
        checkpoint_id: str,
        topology: TopologySnapshot,
        red_target_priority: list[str],
        event_callback: Callable[[str, dict[str, Any]], None] | None,
        should_stop: Callable[[], bool] | None,
        step_delay_s: float,
    ) -> SimulationResult:
        return simulate_episode(
            seed=seed,
            scenario_id=topology.scenario_id,
            checkpoint_id=checkpoint_id,
            defender_mode="ppo",
            horizon=horizon,
            topology_override=topology,
            red_target_priority=red_target_priority,
            event_callback=event_callback,
            should_stop=should_stop,
            step_delay_s=step_delay_s,
        )


class DgxScriptLauncher:
    def __init__(self, script_path: Path) -> None:
        self._script_path = script_path

    def run_episode(
        self,
        *,
        seed: int,
        horizon: int,
        checkpoint_id: str,
        topology: TopologySnapshot,
        red_target_priority: list[str],
        event_callback: Callable[[str, dict[str, Any]], None] | None,
        should_stop: Callable[[], bool] | None,
        step_delay_s: float,
    ) -> SimulationResult:
        _ = seed
        _ = horizon
        _ = checkpoint_id
        _ = topology
        _ = red_target_priority
        _ = event_callback
        _ = should_stop
        _ = step_delay_s

        if not self._script_path.exists():
            raise RuntimeError(f"DGX launcher script not found: {self._script_path}")

        process = subprocess.run(
            [str(self._script_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        raise RuntimeError(
            "DGX launcher is configured but does not provide in-process live event streaming "
            f"(exit={process.returncode})"
        )

