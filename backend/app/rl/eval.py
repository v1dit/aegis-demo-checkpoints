from __future__ import annotations

from pathlib import Path

import orjson

from backend.app.env.simulator import simulate_episode
from backend.app.replay.builder import build_replay_bundle
from backend.app.schemas.contracts import EvalKpis, EvalReport, PerScenarioEval


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _scenario_id_for_suite(suite_id: str) -> str:
    if suite_id == "heldout_suite_v1":
        return "scenario_unseen_web_rce"
    return f"scenario_{suite_id}"


def evaluate_checkpoint(
    *,
    eval_id: str,
    checkpoint_id: str,
    suite_id: str,
    seeds: list[int],
    replay_root: Path,
) -> EvalReport:
    scenario_id = _scenario_id_for_suite(suite_id)
    per_scenario: list[PerScenarioEval] = []

    total_blue_damage = 0.0
    total_none_damage = 0.0
    total_rule_damage = 0.0
    total_blue_latency = 0.0
    total_rule_latency = 0.0

    for index, seed in enumerate(seeds, start=1):
        no_defense = simulate_episode(
            seed=seed,
            scenario_id=scenario_id,
            checkpoint_id="baseline_no_defense",
            defender_mode="none",
        )
        rule_based = simulate_episode(
            seed=seed,
            scenario_id=scenario_id,
            checkpoint_id="baseline_rule_based",
            defender_mode="rule",
        )
        blue = simulate_episode(
            seed=seed,
            scenario_id=scenario_id,
            checkpoint_id=checkpoint_id,
            defender_mode="ppo",
        )

        # Persist deterministic replay artifacts for the trained defender run.
        replay_id = f"replay_eval_{index:02d}"
        build_replay_bundle(sim_result=blue, replay_id=replay_id, replay_root=replay_root)

        total_blue_damage += blue.summary.damage
        total_none_damage += no_defense.summary.damage
        total_rule_damage += rule_based.summary.damage
        total_blue_latency += blue.summary.mean_detection_latency_ms
        total_rule_latency += rule_based.summary.mean_detection_latency_ms

        per_scenario.append(
            PerScenarioEval(
                scenario_id=scenario_id,
                seed=seed,
                blue_damage=blue.summary.damage,
                no_defense_damage=no_defense.summary.damage,
                rule_based_damage=rule_based.summary.damage,
                blue_detection_latency=blue.summary.mean_detection_latency_ms,
                rule_based_detection_latency=rule_based.summary.mean_detection_latency_ms,
            )
        )

    avg_blue_damage = total_blue_damage / len(seeds)
    avg_none_damage = total_none_damage / len(seeds)
    avg_rule_damage = total_rule_damage / len(seeds)
    avg_blue_latency = total_blue_latency / len(seeds)
    avg_rule_latency = total_rule_latency / len(seeds)

    damage_vs_none = 1.0 - _safe_ratio(avg_blue_damage, avg_none_damage)
    damage_vs_rule = 1.0 - _safe_ratio(avg_blue_damage, avg_rule_damage)
    latency_improvement = 1.0 - _safe_ratio(avg_blue_latency, avg_rule_latency)

    # Keep numeric shape stable for dashboard display.
    kpis = EvalKpis(
        damage_reduction_vs_no_defense=round(max(-1.0, damage_vs_none), 4),
        damage_reduction_vs_rule_based=round(max(-1.0, damage_vs_rule), 4),
        detection_latency_improvement_vs_rule_based=round(max(-1.0, latency_improvement), 4),
    )

    return EvalReport(
        eval_id=eval_id,
        suite_id=suite_id,
        kpis=kpis,
        per_scenario=per_scenario,
    )


def write_eval_report(report: EvalReport, report_dir: Path) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    output = report_dir / f"{report.eval_id}.json"
    output.write_bytes(orjson.dumps(report.model_dump(mode="json"), option=orjson.OPT_INDENT_2))
    latest = report_dir / "eval_report_latest.json"
    latest.write_bytes(orjson.dumps(report.model_dump(mode="json"), option=orjson.OPT_INDENT_2))
    return output


def acceptance_gate_status(report: EvalReport) -> dict[str, bool]:
    return {
        "damage_reduction_vs_no_defense": report.kpis.damage_reduction_vs_no_defense >= 0.25,
        "damage_reduction_vs_rule_based": report.kpis.damage_reduction_vs_rule_based >= 0.15,
        "detection_latency_improvement_vs_rule_based": (
            report.kpis.detection_latency_improvement_vs_rule_based >= 0.20
        ),
    }
