from __future__ import annotations

import importlib.util
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.env.topology import generate_topology
from backend.app.rl.actions import BLUE_ACTIONS
from backend.app.rl.policy_features import (
    OBSERVATION_DIM,
    action_type_for_index,
    build_policy_observation,
)
from backend.app.rl.red_policy import ScriptedRedPolicy
from backend.app.rl.reward import compute_blue_reward
from backend.app.rl.reward_shaping import (
    ActionRepeatTracker,
    prevention_success_for_transition,
    repeat_penalty_probe_events,
    survival_bonus_for_step,
)


class RLlibUnavailableError(RuntimeError):
    pass


@dataclass
class PreflightGateStatus:
    passed: bool
    errors: list[str]


def rllib_available() -> bool:
    return (
        importlib.util.find_spec("ray") is not None
        and importlib.util.find_spec("gymnasium") is not None
    )


def _checkpoint_path(checkpoint_ref: Any) -> str:
    if isinstance(checkpoint_ref, str):
        return checkpoint_ref
    to_path = getattr(checkpoint_ref, "to_directory", None)
    if callable(to_path):
        return str(to_path())
    path = getattr(checkpoint_ref, "path", None)
    if path:
        return str(path)
    return str(checkpoint_ref)


def compute_deterministic_action(algo: Any, observation: list[float]) -> int:
    try:
        prediction = algo.compute_single_action(observation, explore=False)
    except TypeError:
        prediction = algo.compute_single_action(observation)
    if isinstance(prediction, tuple):
        return int(prediction[0])
    return int(prediction)


def _first_finite_number(values: list[Any]) -> float | None:
    for value in values:
        if isinstance(value, int | float):
            numeric = float(value)
            if math.isfinite(numeric):
                return numeric
    return None


def extract_policy_entropy(result: dict[str, Any]) -> float | None:
    candidates: list[Any] = [
        result.get("policy_entropy"),
        result.get("entropy"),
    ]

    info = result.get("info", {})
    if isinstance(info, dict):
        learner = info.get("learner", {})
        if isinstance(learner, dict):
            for row in learner.values():
                if not isinstance(row, dict):
                    continue
                stats = row.get("learner_stats", {})
                if isinstance(stats, dict):
                    candidates.extend(
                        [
                            stats.get("entropy"),
                            stats.get("policy_entropy"),
                            stats.get("mean_entropy"),
                        ]
                    )

    learner_results = result.get("learner_results", {})
    if isinstance(learner_results, dict):
        for row in learner_results.values():
            if not isinstance(row, dict):
                continue
            stats = row.get("learner_stats", {})
            if isinstance(stats, dict):
                candidates.extend(
                    [
                        stats.get("entropy"),
                        stats.get("policy_entropy"),
                        stats.get("mean_entropy"),
                    ]
                )

    return _first_finite_number(candidates)


def preflight_gate_status(
    result: dict[str, Any],
    *,
    min_entropy: float = 0.01,
) -> PreflightGateStatus:
    errors: list[str] = []
    learning_metrics = result.get("learning_metrics", {})
    if not isinstance(learning_metrics, dict):
        errors.append("learning_metrics_missing")
        return PreflightGateStatus(passed=False, errors=errors)

    reward_mean = learning_metrics.get("episode_reward_mean")
    timesteps_total = learning_metrics.get("timesteps_total")
    policy_entropy = learning_metrics.get("policy_entropy")

    if not isinstance(reward_mean, int | float) or not math.isfinite(float(reward_mean)):
        errors.append("episode_reward_mean_invalid")
    if not isinstance(timesteps_total, int | float) or not math.isfinite(float(timesteps_total)):
        errors.append("timesteps_total_invalid")
    if not isinstance(policy_entropy, int | float):
        errors.append("policy_entropy_missing")
    elif not math.isfinite(float(policy_entropy)):
        errors.append("policy_entropy_invalid")
    elif float(policy_entropy) <= min_entropy:
        errors.append("policy_entropy_collapsed")

    repeat_probe = result.get("reward_shaping_probe_repeat_penalties")
    if not isinstance(repeat_probe, int | float):
        errors.append("repeat_penalty_probe_missing")
    elif float(repeat_probe) <= 0:
        errors.append("repeat_penalty_probe_not_triggered")

    return PreflightGateStatus(passed=not errors, errors=errors)


def _extract_custom_metric(result: dict[str, Any], name: str) -> float | None:
    custom_metrics = result.get("custom_metrics", {})
    if not isinstance(custom_metrics, dict):
        return None
    return _first_finite_number(
        [
            custom_metrics.get(name),
            custom_metrics.get(f"{name}_mean"),
        ]
    )


def restore_algorithm_from_checkpoint(checkpoint_path: str) -> Any:
    if not rllib_available():
        raise RLlibUnavailableError("ray[rllib] and gymnasium are required for PPO inference")
    try:
        from ray.rllib.algorithms.algorithm import Algorithm
    except Exception as exc:  # pragma: no cover - import guard
        raise RLlibUnavailableError("Failed to import RLlib Algorithm API") from exc
    return Algorithm.from_checkpoint(checkpoint_path)


@dataclass
class _HostRuntime:
    compromised: bool = False
    defense_state: str = "none"
    isolated: bool = False


def _apply_blue_action(
    *,
    action_type: str,
    target_host: str,
    target_service: str | None,
    runtime: dict[str, _HostRuntime],
    edge_status: dict[str, str],
    recent_red_target: str,
    cumulative_damage: float,
    repeat_tracker: ActionRepeatTracker,
    step: int,
) -> tuple[float, bool, float, float, bool, float, bool]:
    containment_success = False
    false_positive_cost = 0.0
    isolation_cost = 0.0
    meaningful_state_change = False

    target_state = runtime[target_host]
    previous_defense_state = target_state.defense_state
    was_compromised = target_state.compromised
    if action_type == "monitor_host":
        if target_state.defense_state != "monitored":
            target_state.defense_state = "monitored"
            meaningful_state_change = True
    elif action_type == "patch_service":
        _ = target_service
        if target_state.defense_state not in {"hardened", "monitored"}:
            target_state.defense_state = "hardened"
            meaningful_state_change = True
            if not target_state.compromised:
                cumulative_damage = max(0.0, cumulative_damage - 0.15)
    elif action_type == "isolate_host":
        if target_state.defense_state != "isolated" or not target_state.isolated:
            meaningful_state_change = True
        target_state.defense_state = "isolated"
        target_state.isolated = True
        containment_success = target_state.compromised
        if containment_success:
            cumulative_damage = max(0.0, cumulative_damage - 0.45)
        isolation_cost = 0.15
        for edge_id in sorted(edge_status.keys()):
            if target_host in edge_id and edge_status[edge_id] == "active":
                edge_status[edge_id] = "blocked"
                meaningful_state_change = True
    elif action_type == "block_connection":
        for edge_id in sorted(edge_status.keys()):
            if recent_red_target in edge_id and edge_status[edge_id] == "active":
                edge_status[edge_id] = "blocked"
                containment_success = True
                meaningful_state_change = True
                break
    elif action_type == "rotate_credentials":
        if target_state.defense_state != "hardened":
            target_state.defense_state = "hardened"
            meaningful_state_change = True
    elif action_type == "deploy_deception":
        if target_state.defense_state != "deception":
            target_state.defense_state = "deception"
            meaningful_state_change = True

    if not target_state.compromised and action_type in {"isolate_host", "block_connection"}:
        false_positive_cost = 0.05

    prevention_success = prevention_success_for_transition(
        action_type=action_type,
        was_compromised=was_compromised,
        previous_defense_state=previous_defense_state,
        new_defense_state=target_state.defense_state,
        meaningful_state_change=meaningful_state_change,
    )
    action_repeat_penalty = repeat_tracker.penalty_for(
        action_type=action_type,
        target_host=target_host,
        step=step,
        meaningful_state_change=meaningful_state_change,
    )

    return (
        cumulative_damage,
        containment_success,
        false_positive_cost,
        isolation_cost,
        prevention_success,
        action_repeat_penalty,
        meaningful_state_change,
    )


def run_ppo_training(config: dict[str, Any]) -> dict[str, Any]:
    if not rllib_available():
        raise RLlibUnavailableError("ray[rllib] and gymnasium are not installed")

    try:
        import gymnasium as gym
        import numpy as np
        import ray
        from gymnasium import spaces
        from ray.rllib.algorithms.ppo import PPOConfig
        from ray.tune.registry import register_env
    except Exception as exc:  # pragma: no cover - import guard
        raise RLlibUnavailableError("Failed to import PPO dependencies") from exc

    class BlueDefenseGymEnv(gym.Env):
        metadata = {"render_modes": []}

        def __init__(self, env_config: dict[str, Any]) -> None:
            self._base_seed = int(env_config.get("seed", 42))
            self._scenario_id = str(env_config.get("scenario_id", "scenario_unseen_web_rce"))
            self._horizon = int(env_config.get("horizon", 200))
            self._red_stochastic_probability = float(
                env_config.get("red_stochastic_probability", 0.3)
            )
            self._seed_rng = random.Random(
                self._base_seed
                + int(env_config.get("worker_index", 0)) * 10000
                + int(env_config.get("vector_index", 0)) * 1000
            )
            self._episode_seed = self._base_seed
            self._step = 0

            self.action_space = spaces.Discrete(len(BLUE_ACTIONS))
            self.observation_space = spaces.Box(
                low=0.0,
                high=1.0,
                shape=(OBSERVATION_DIM,),
                dtype=np.float32,
            )

            self._hosts: list[str] = []
            self._services_by_host: dict[str, list[str]] = {}
            self._runtime: dict[str, _HostRuntime] = {}
            self._edge_status: dict[str, str] = {}
            self._red_policy = ScriptedRedPolicy(seed=self._base_seed)
            self._recent_red_target = ""
            self._cumulative_damage = 0.0
            self._repeat_tracker = ActionRepeatTracker()
            self._prevention_events = 0
            self._repeat_penalty_events = 0

        def _observation(self) -> np.ndarray:
            compromised_hosts = {
                host for host, state in self._runtime.items() if state.compromised
            }
            values = build_policy_observation(
                step=self._step,
                horizon=self._horizon,
                hosts=self._hosts,
                compromised_hosts=compromised_hosts,
                recent_red_target=self._recent_red_target,
            )
            return np.asarray(values, dtype=np.float32)

        def reset(self, *, seed: int | None = None, options: dict | None = None):
            super().reset(seed=seed)
            if seed is not None:
                self._seed_rng.seed(seed)
            self._episode_seed = self._seed_rng.randint(1, 10_000_000)
            self._step = 0
            self._cumulative_damage = 0.0
            topology = generate_topology(seed=self._episode_seed, scenario_id=self._scenario_id)
            self._hosts = [node.node_id for node in topology.nodes]
            self._services_by_host = {node.node_id: node.services for node in topology.nodes}
            self._runtime = {host: _HostRuntime() for host in self._hosts}
            self._edge_status = {edge.edge_id: edge.status for edge in topology.edges}
            self._red_policy = ScriptedRedPolicy(
                seed=self._episode_seed,
                stochastic_branch_probability=self._red_stochastic_probability,
            )
            self._recent_red_target = self._hosts[0]
            self._repeat_tracker = ActionRepeatTracker()
            self._prevention_events = 0
            self._repeat_penalty_events = 0
            return self._observation(), {}

        def step(self, action: int):
            self._step += 1
            red_decision = self._red_policy.decide(
                step=self._step,
                hosts=self._hosts,
                service_lookup=self._services_by_host,
            )
            self._recent_red_target = red_decision.target_host
            red_target_runtime = self._runtime[red_decision.target_host]

            exploit_penalty = 0.0
            if red_target_runtime.defense_state in {"hardened", "deception"}:
                exploit_penalty += 0.2
            if red_target_runtime.isolated:
                exploit_penalty += 0.3

            step_rng = random.Random(self._episode_seed * 409 + self._step)
            exploit_probability = max(0.05, min(0.95, 0.55 - exploit_penalty - 0.08))
            red_success = False
            exfil_success = False
            new_compromise = False

            if red_decision.action_type in {
                "exploit_vulnerability",
                "lateral_move",
                "privilege_escalate",
            }:
                target_was_compromised = red_target_runtime.compromised
                red_success = step_rng.random() < exploit_probability
                if red_success:
                    red_target_runtime.compromised = True
                    new_compromise = not target_was_compromised
                    self._cumulative_damage += 1.6

            if red_decision.action_type == "exfiltrate_data":
                source = self._runtime[red_decision.source_host]
                exfil_success = source.compromised and not source.isolated
                if exfil_success:
                    self._cumulative_damage += 2.2

            compromised_hosts = {
                host for host, state in self._runtime.items() if state.compromised
            }
            action_type = action_type_for_index(int(action))
            target_host = self._recent_red_target
            if action_type == "isolate_host" and compromised_hosts:
                target_host = sorted(compromised_hosts)[0]
            target_service = None
            if action_type == "patch_service":
                target_service = self._services_by_host[target_host][0]

            (
                self._cumulative_damage,
                containment_success,
                false_positive_cost,
                isolation_cost,
                prevention_success,
                action_repeat_penalty,
                _,
            ) = _apply_blue_action(
                action_type=action_type,
                target_host=target_host,
                target_service=target_service,
                runtime=self._runtime,
                edge_status=self._edge_status,
                recent_red_target=self._recent_red_target,
                cumulative_damage=self._cumulative_damage,
                repeat_tracker=self._repeat_tracker,
                step=self._step,
            )
            if prevention_success:
                self._prevention_events += 1
            if action_repeat_penalty > 0:
                self._repeat_penalty_events += 1

            monitored_target = self._runtime[self._recent_red_target]
            detect_prob = 0.3
            if monitored_target.defense_state in {"monitored", "deception"}:
                detect_prob += 0.45
            if monitored_target.compromised:
                detect_prob += 0.2
            detect_prob += 0.15
            detected = step_rng.random() < min(0.98, detect_prob)

            reward = compute_blue_reward(
                compromise_success=red_success,
                exfil_success=exfil_success,
                detection_success=detected,
                containment_success=containment_success,
                false_positive_cost=false_positive_cost,
                isolation_cost=isolation_cost,
                prevention_success=prevention_success,
                survival_bonus=survival_bonus_for_step(
                    exfil_success=exfil_success,
                    new_compromise=new_compromise,
                ),
                service_disruption_penalty=(false_positive_cost + isolation_cost),
                action_repeat_penalty=action_repeat_penalty,
            )
            terminated = self._step >= self._horizon
            info = {}
            if terminated:
                info = {
                    "prevention_events": float(self._prevention_events),
                    "repeat_penalty_events": float(self._repeat_penalty_events),
                }
            return self._observation(), reward, terminated, False, info

    checkpoint_output_dir = Path(str(config["checkpoint_output_dir"]))
    checkpoint_output_dir.mkdir(parents=True, exist_ok=True)

    env_name = f"cyber_range_blue_v0_{abs(hash(str(checkpoint_output_dir))) % 10_000_000}"

    try:
        register_env(env_name, lambda env_config: BlueDefenseGymEnv(env_config))
    except Exception:
        pass

    run_id = str(config.get("run_id", "run_unknown"))
    max_timesteps = int(config.get("max_timesteps", 100000))
    train_batch_size = int(config.get("train_batch_size", 4000))
    configured_iterations = int(config.get("max_iterations", 0))
    target_iterations = (
        max(1, configured_iterations)
        if configured_iterations > 0
        else max(1, math.ceil(max_timesteps / float(max(1, train_batch_size))))
    )
    env_config = {
        "seed": int(config.get("seed", 42)),
        "scenario_id": str(config.get("scenario_id", "scenario_unseen_web_rce")),
        "horizon": int(config.get("horizon", 200)),
        "red_stochastic_probability": float(config.get("red_stochastic_probability", 0.3)),
    }

    config_obj = (
        PPOConfig()
        .environment(env=env_name, env_config=env_config)
        .framework("torch")
        .training(
            lr=float(config.get("lr", 3e-4)),
            gamma=float(config.get("gamma", 0.99)),
            train_batch_size=train_batch_size,
            model={"fcnet_hiddens": [128, 128], "fcnet_activation": "relu"},
        )
        .resources(
            num_gpus=float(config.get("num_gpus", 0)),
        )
    )

    if hasattr(config_obj, "rollouts"):
        config_obj = config_obj.rollouts(
            num_rollout_workers=int(config.get("num_rollout_workers", 0))
        )
    elif hasattr(config_obj, "env_runners"):  # pragma: no cover - Ray API variation
        config_obj = config_obj.env_runners(
            num_env_runners=int(config.get("num_rollout_workers", 0))
        )

    started_ray = False
    if not ray.is_initialized():
        ray.init(
            ignore_reinit_error=True,
            include_dashboard=False,
            logging_level="ERROR",
        )
        started_ray = True

    algo = None
    metrics_history: list[dict[str, float]] = []
    try:
        algo = config_obj.build()
        for index in range(1, target_iterations + 1):
            result = algo.train()
            policy_entropy = extract_policy_entropy(result)
            iteration_metrics = {
                "iteration": float(index),
                "episode_reward_mean": float(result.get("episode_reward_mean", 0.0)),
                "episode_len_mean": float(result.get("episode_len_mean", 0.0)),
                "timesteps_total": float(
                    result.get(
                        "timesteps_total",
                        result.get("num_env_steps_sampled_lifetime", index * train_batch_size),
                    )
                ),
                "policy_entropy": float(policy_entropy) if policy_entropy is not None else 0.0,
                "prevention_events": float(_extract_custom_metric(result, "prevention_events") or 0.0),
                "repeat_penalty_events": float(
                    _extract_custom_metric(result, "repeat_penalty_events") or 0.0
                ),
            }
            metrics_history.append(iteration_metrics)
            if iteration_metrics["timesteps_total"] >= max_timesteps:
                break

        checkpoint_ref = algo.save(checkpoint_dir=str(checkpoint_output_dir))
        checkpoint_path = _checkpoint_path(checkpoint_ref)
    finally:
        if algo is not None:
            try:
                algo.stop()
            except Exception:  # pragma: no cover - defensive cleanup
                pass
        if started_ray and ray.is_initialized():
            ray.shutdown()

    final_metrics = metrics_history[-1] if metrics_history else {
        "episode_reward_mean": 0.0,
        "episode_len_mean": 0.0,
        "timesteps_total": float(max_timesteps),
        "policy_entropy": 0.0,
        "prevention_events": 0.0,
        "repeat_penalty_events": 0.0,
    }
    repeat_probe = repeat_penalty_probe_events()
    return {
        "trainer": "rllib_ppo",
        "status": "completed",
        "run_id": run_id,
        "rllib_checkpoint_path": checkpoint_path,
        "timesteps_total": int(final_metrics["timesteps_total"]),
        "learning_metrics": {
            "episode_reward_mean": round(float(final_metrics["episode_reward_mean"]), 6),
            "episode_len_mean": round(float(final_metrics["episode_len_mean"]), 6),
            "timesteps_total": int(final_metrics["timesteps_total"]),
            "policy_entropy": round(float(final_metrics["policy_entropy"]), 6),
            "prevention_events": round(float(final_metrics["prevention_events"]), 6),
            "repeat_penalty_events": round(float(final_metrics["repeat_penalty_events"]), 6),
        },
        "seed_strategy": {
            "base_seed": int(config.get("seed", 42)),
            "episode_seed_mode": "per-episode-randomized",
            "red_stochastic_probability": float(config.get("red_stochastic_probability", 0.3)),
        },
        "ppo_config": {
            "lr": float(config.get("lr", 3e-4)),
            "gamma": float(config.get("gamma", 0.99)),
            "train_batch_size": int(config.get("train_batch_size", 4000)),
            "num_rollout_workers": int(config.get("num_rollout_workers", 0)),
            "horizon": int(config.get("horizon", 200)),
            "scenario_id": str(config.get("scenario_id", "scenario_unseen_web_rce")),
        },
        "reward_shaping_probe_repeat_penalties": repeat_probe,
        "iterations": metrics_history,
    }
