from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Literal

from backend.app.core.runs import read_checkpoint_payload
from backend.app.env.catalog import MITRE_TACTIC_BY_ACTION
from backend.app.env.clock import StepClock
from backend.app.env.topology import generate_topology
from backend.app.explainability.reasoner import build_explainability_record
from backend.app.rl.blue_policy import BlueDecision, policy_for
from backend.app.rl.red_policy import ScriptedRedPolicy
from backend.app.rl.reward import compute_blue_reward
from backend.app.rl.reward_shaping import (
    ActionRepeatTracker,
    prevention_success_for_transition,
    survival_bonus_for_step,
)
from backend.app.schemas.contracts import (
    ActionEvent,
    DetectionEvent,
    EdgeChange,
    ExplainabilityRecord,
    NodeChange,
    StateDelta,
)
from backend.app.schemas.topology import TopologySnapshot


@dataclass
class SimulationMetrics:
    damage: float
    mean_detection_latency_ms: float
    attack_success_rate: float
    rewards_sum: float
    exfiltration_count: int
    exfiltration_attempts: int
    critical_asset_compromise_rate: float


@dataclass
class SimulationResult:
    scenario_id: str
    seed: int
    checkpoint_id: str
    defender_mode: str
    topology: TopologySnapshot
    events: list[dict]
    state_deltas: list[StateDelta]
    explainability: list[ExplainabilityRecord]
    metrics_series: list[dict]
    summary: SimulationMetrics


@dataclass
class _HostRuntime:
    compromised: bool = False
    defense_state: str = "none"
    isolated: bool = False
    first_compromise_step: int | None = None
    first_detect_step: int | None = None


def _confidence(seed: int, step: int, bonus: float = 0.0) -> float:
    rng = random.Random(seed * 131 + step)
    return round(min(0.99, 0.55 + rng.random() * 0.4 + bonus), 2)


def simulate_episode(
    *,
    seed: int,
    scenario_id: str,
    checkpoint_id: str,
    defender_mode: Literal["none", "rule", "ppo"],
    checkpoint_bias: float | None = None,
    checkpoint_payload: dict[str, Any] | None = None,
    run_id: str | None = None,
    horizon: int = 200,
) -> SimulationResult:
    topology = generate_topology(seed=seed, scenario_id=scenario_id)
    hosts = [node.node_id for node in topology.nodes]
    services_by_host = {node.node_id: node.services for node in topology.nodes}

    runtime = {host: _HostRuntime() for host in hosts}
    edge_status = {edge.edge_id: edge.status for edge in topology.edges}

    resolved_payload = checkpoint_payload
    if defender_mode == "ppo" and resolved_payload is None:
        resolved_payload = read_checkpoint_payload(checkpoint_id=checkpoint_id, run_id=run_id)
    legacy_checkpoint_bias = checkpoint_bias
    if legacy_checkpoint_bias is None and resolved_payload and "policy_bias" in resolved_payload:
        legacy_checkpoint_bias = float(resolved_payload["policy_bias"])

    red_policy = ScriptedRedPolicy(seed=seed)
    blue_policy = policy_for(
        mode=defender_mode,
        seed=seed + 17,
        checkpoint_bias=legacy_checkpoint_bias,
        checkpoint_payload=resolved_payload,
        horizon=horizon,
    )
    clock = StepClock(start_ts_ms=1712412345000 + (seed * 11))

    action_events: list[ActionEvent] = []
    detection_events: list[DetectionEvent] = []
    state_deltas: list[StateDelta] = []
    explainability: list[ExplainabilityRecord] = []
    metrics_series: list[dict] = []

    attack_successes = 0
    cumulative_damage = 0.0
    rewards_sum = 0.0
    exfiltration_count = 0
    exfiltration_attempts = 0
    detection_latencies: list[float] = []
    prevention_events = 0
    repeat_penalty_events = 0

    action_counter = 1
    detect_counter = 1
    recent_red_target = hosts[0]
    repeat_tracker = ActionRepeatTracker()
    critical_hosts = {
        node.node_id
        for node in topology.nodes
        if node.zone in {"data", "identity", "saas"}
        or node.asset_type in {"idp", "crm_saas", "data_store"}
    }

    for step in range(1, horizon + 1):
        red_decision = red_policy.decide(step, hosts, services_by_host)
        recent_red_target = red_decision.target_host

        red_success = False
        exfil_success = False
        new_compromise = False
        changed_nodes: list[NodeChange] = []
        changed_edges: list[EdgeChange] = []

        red_target_runtime = runtime[red_decision.target_host]
        exploit_penalty = 0.0
        if red_target_runtime.defense_state in {"hardened", "deception"}:
            exploit_penalty += 0.2
        if red_target_runtime.isolated:
            exploit_penalty += 0.3

        exploit_probability = 0.55 - exploit_penalty
        if defender_mode == "ppo":
            exploit_probability -= 0.08
            if legacy_checkpoint_bias is not None:
                exploit_probability -= legacy_checkpoint_bias * 0.06
        if defender_mode == "none":
            exploit_probability += 0.15

        step_rng = random.Random(seed * 409 + step)

        if red_decision.action_type in {
            "exploit_vulnerability",
            "lateral_move",
            "privilege_escalate",
        }:
            target_was_compromised = red_target_runtime.compromised
            red_success = step_rng.random() < max(0.05, min(0.95, exploit_probability))
            if red_success:
                red_target_runtime.compromised = True
                new_compromise = not target_was_compromised
                if red_target_runtime.first_compromise_step is None:
                    red_target_runtime.first_compromise_step = step
                attack_successes += 1
                cumulative_damage += 1.6
                changed_nodes.append(
                    NodeChange(
                        node_id=red_decision.target_host,
                        compromise_state="compromised",
                        defense_state=red_target_runtime.defense_state,
                    )
                )

        if red_decision.action_type == "exfiltrate_data":
            exfiltration_attempts += 1
            source = runtime[red_decision.source_host]
            exfil_success = source.compromised and not source.isolated
            if exfil_success:
                exfiltration_count += 1
                cumulative_damage += 2.2
                attack_successes += 1

        action_events.append(
            ActionEvent(
                event_id=f"evt_{action_counter:06d}",
                ts_ms=clock.ts(step, 0),
                step=step,
                actor="RED",
                action_type=red_decision.action_type,
                source_host=red_decision.source_host,
                target_host=red_decision.target_host,
                target_service=red_decision.target_service,
                outcome="success" if red_success or exfil_success else "blocked",
                mitre_tactic=MITRE_TACTIC_BY_ACTION[red_decision.action_type],
                confidence=_confidence(seed, step, 0.06),
            )
        )
        action_counter += 1

        blue_decision: BlueDecision | None = blue_policy.decide(
            step=step,
            hosts=hosts,
            compromised_hosts={host for host, state in runtime.items() if state.compromised},
            recent_red_target=recent_red_target,
            services_by_host=services_by_host,
        )

        detected = False
        if defender_mode != "none":
            monitored_target = runtime[recent_red_target]
            detect_prob = 0.3
            if monitored_target.defense_state in {"monitored", "deception"}:
                detect_prob += 0.45
            if monitored_target.compromised:
                detect_prob += 0.2
            if defender_mode == "ppo":
                detect_prob += 0.15
            detected = step_rng.random() < min(0.98, detect_prob)
            if detected:
                if monitored_target.first_detect_step is None:
                    monitored_target.first_detect_step = step
                detection_events.append(
                    DetectionEvent(
                        event_id=f"det_{detect_counter:06d}",
                        ts_ms=clock.ts(step, 6),
                        step=step,
                        detector="BLUE",
                        target_host=recent_red_target,
                        signal="traffic_spike",
                        severity="high" if monitored_target.compromised else "medium",
                        detected=True,
                    )
                )
                detect_counter += 1

        containment_success = False
        false_positive_cost = 0.0
        isolation_cost = 0.0
        prevention_success = False
        action_repeat_penalty = 0.0
        service_disruption_penalty = 0.0
        meaningful_state_change = False

        if blue_decision is not None:
            target_state = runtime[blue_decision.target_host]
            previous_defense_state = target_state.defense_state
            target_was_compromised = target_state.compromised
            if blue_decision.action_type == "monitor_host":
                if target_state.defense_state != "monitored":
                    target_state.defense_state = "monitored"
                    meaningful_state_change = True
            elif blue_decision.action_type == "patch_service":
                if target_state.defense_state not in {"hardened", "monitored"}:
                    target_state.defense_state = "hardened"
                    meaningful_state_change = True
                    if not target_state.compromised:
                        cumulative_damage = max(0.0, cumulative_damage - 0.15)
            elif blue_decision.action_type == "isolate_host":
                if target_state.defense_state != "isolated" or not target_state.isolated:
                    meaningful_state_change = True
                target_state.defense_state = "isolated"
                target_state.isolated = True
                containment_success = target_state.compromised
                if containment_success:
                    cumulative_damage = max(0.0, cumulative_damage - 0.45)
                isolation_cost = 0.15
                for edge_id in sorted(edge_status.keys()):
                    if blue_decision.target_host in edge_id and edge_status[edge_id] == "active":
                        edge_status[edge_id] = "blocked"
                        changed_edges.append(EdgeChange(edge_id=edge_id, status="blocked"))
                        meaningful_state_change = True
            elif blue_decision.action_type == "block_connection":
                for edge_id in sorted(edge_status.keys()):
                    if recent_red_target in edge_id and edge_status[edge_id] == "active":
                        edge_status[edge_id] = "blocked"
                        changed_edges.append(EdgeChange(edge_id=edge_id, status="blocked"))
                        containment_success = True
                        meaningful_state_change = True
                        break
            elif blue_decision.action_type == "rotate_credentials":
                if target_state.defense_state != "hardened":
                    target_state.defense_state = "hardened"
                    meaningful_state_change = True
            elif blue_decision.action_type == "deploy_deception":
                if target_state.defense_state != "deception":
                    target_state.defense_state = "deception"
                    meaningful_state_change = True

            if (
                not target_state.compromised
                and blue_decision.action_type in {"isolate_host", "block_connection"}
            ):
                false_positive_cost = 0.05

            prevention_success = prevention_success_for_transition(
                action_type=blue_decision.action_type,
                was_compromised=target_was_compromised,
                previous_defense_state=previous_defense_state,
                new_defense_state=target_state.defense_state,
                meaningful_state_change=meaningful_state_change,
            )
            if prevention_success:
                prevention_events += 1
            action_repeat_penalty = repeat_tracker.penalty_for(
                blue_decision.action_type,
                blue_decision.target_host,
                step=step,
                meaningful_state_change=meaningful_state_change,
            )
            if action_repeat_penalty > 0:
                repeat_penalty_events += 1
            service_disruption_penalty = false_positive_cost + isolation_cost

            action_events.append(
                ActionEvent(
                    event_id=f"evt_{action_counter:06d}",
                    ts_ms=clock.ts(step, 8),
                    step=step,
                    actor="BLUE",
                    action_type=blue_decision.action_type,
                    source_host="soc_01",
                    target_host=blue_decision.target_host,
                    target_service=blue_decision.target_service,
                    outcome="success",
                    mitre_tactic=MITRE_TACTIC_BY_ACTION[blue_decision.action_type],
                    confidence=_confidence(seed + 17, step, 0.12),
                )
            )
            action_counter += 1

            explainability.append(
                build_explainability_record(
                    ts_ms=clock.ts(step, 10),
                    step=step,
                    action=blue_decision.action_type,
                    target_host=blue_decision.target_host,
                    confidence=_confidence(seed + 42, step),
                    compromised_count=sum(1 for state in runtime.values() if state.compromised),
                    detections_count=len(detection_events),
                )
            )

        rewards_sum += compute_blue_reward(
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
            service_disruption_penalty=service_disruption_penalty,
            action_repeat_penalty=action_repeat_penalty,
        )

        if changed_nodes or changed_edges:
            state_deltas.append(
                StateDelta(
                    ts_ms=clock.ts(step, 2),
                    step=step,
                    node_changes=changed_nodes,
                    edge_changes=changed_edges,
                )
            )

        action_events.append(
            ActionEvent(
                event_id=f"evt_{action_counter:06d}",
                ts_ms=clock.ts(step, 15),
                step=step,
                actor="ENV",
                action_type="step_marker",
                source_host="engine",
                target_host="engine",
                target_service=None,
                outcome="tick",
                mitre_tactic=MITRE_TACTIC_BY_ACTION["step_marker"],
                confidence=1.0,
            )
        )
        action_counter += 1

        for host_state in runtime.values():
            if (
                host_state.first_compromise_step is not None
                and host_state.first_detect_step is not None
            ):
                latency_ms = (
                    host_state.first_detect_step - host_state.first_compromise_step
                ) * clock.step_ms
                if latency_ms >= 0:
                    detection_latencies.append(float(latency_ms))
                host_state.first_compromise_step = None
                host_state.first_detect_step = None

        metrics_series.append(
            {
                "ts_ms": clock.ts(step, 12),
                "step": step,
                "damage_score": round(cumulative_damage, 4),
                "compromised_hosts": sum(1 for state in runtime.values() if state.compromised),
                "rewards_sum": round(rewards_sum, 4),
                "detection_count": len(detection_events),
                "prevention_events": prevention_events,
                "repeat_penalty_events": repeat_penalty_events,
            }
        )

    mean_latency = (
        sum(detection_latencies) / len(detection_latencies)
        if detection_latencies
        else float(clock.step_ms * horizon)
    )
    attack_success_rate = attack_successes / float(horizon)
    compromised_critical_hosts = sum(
        1 for host in critical_hosts if runtime.get(host) and runtime[host].compromised
    )
    critical_asset_compromise_rate = compromised_critical_hosts / float(max(1, len(critical_hosts)))

    ordered_events = [
        item.model_dump(mode="json")
        for item in sorted(action_events, key=lambda event: (event.ts_ms, event.event_id))
    ] + [
        item.model_dump(mode="json")
        for item in sorted(detection_events, key=lambda event: (event.ts_ms, event.event_id))
    ]
    ordered_events = sorted(ordered_events, key=lambda item: (item["ts_ms"], item["event_id"]))

    summary = SimulationMetrics(
        damage=round(cumulative_damage, 4),
        mean_detection_latency_ms=round(mean_latency, 2),
        attack_success_rate=round(attack_success_rate, 4),
        rewards_sum=round(rewards_sum, 4),
        exfiltration_count=exfiltration_count,
        exfiltration_attempts=exfiltration_attempts,
        critical_asset_compromise_rate=round(critical_asset_compromise_rate, 4),
    )

    return SimulationResult(
        scenario_id=scenario_id,
        seed=seed,
        checkpoint_id=checkpoint_id,
        defender_mode=defender_mode,
        topology=topology,
        events=ordered_events,
        state_deltas=state_deltas,
        explainability=sorted(explainability, key=lambda row: (row.ts_ms, row.step)),
        metrics_series=sorted(metrics_series, key=lambda row: row["ts_ms"]),
        summary=summary,
    )
