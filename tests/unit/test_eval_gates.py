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
