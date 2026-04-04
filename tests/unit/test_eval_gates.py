from backend.app.rl.eval import acceptance_gate_status, evaluate_checkpoint


def test_eval_report_shape_and_gate_keys(tmp_path) -> None:
    report = evaluate_checkpoint(
        eval_id="eval_test_001",
        checkpoint_id="ckpt_blue_main_0009",
        suite_id="heldout_suite_v1",
        seeds=[1001, 1002, 1003, 1004],
        replay_root=tmp_path,
    )
    gates = acceptance_gate_status(report)

    assert set(gates) == {
        "damage_reduction_vs_no_defense",
        "damage_reduction_vs_rule_based",
        "detection_latency_improvement_vs_rule_based",
    }
    assert report.per_scenario


def test_enterprise_eval_emits_extended_kpis(tmp_path) -> None:
    report = evaluate_checkpoint(
        eval_id="eval_enterprise_test_001",
        checkpoint_id="ckpt_blue_main_0009",
        suite_id="enterprise_suite_v1",
        seeds=[1001, 1002],
        replay_root=tmp_path,
    )

    assert report.per_scenario
    assert report.per_scenario[0].scenario_id.startswith("scenario_enterprise_")
    assert report.kpis.exfiltration_prevention_rate is not None
    assert report.kpis.critical_asset_compromise_rate is not None
    assert 0.0 <= report.kpis.exfiltration_prevention_rate <= 1.0
    assert 0.0 <= report.kpis.critical_asset_compromise_rate <= 1.0
