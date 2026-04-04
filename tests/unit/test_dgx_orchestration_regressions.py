from pathlib import Path

from backend.app.cli import _run_eval
from backend.app.schemas.contracts import EvalKpis, EvalReport


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_cluster_exec_waits_for_long_running_commands_and_propagates_exit_code() -> None:
    script = _read("ops/scripts/cluster_exec.expect")

    assert "set timeout -1" in script
    assert "set wait_status [wait]" in script
    assert "set exit_code [lindex $wait_status 3]" in script
    assert "exit $exit_code" in script


def test_train_container_uses_configurable_git_ref_not_hardcoded_main() -> None:
    script = _read("ops/scripts/dgx_train_container.sh")

    assert "git checkout main" not in script
    assert 'TARGET_REF="${DGX_GIT_REF:-' in script
    assert 'git fetch origin "\\$TARGET_REF"' in script


def test_eval_container_has_same_gpu_fallback_strategy_as_train() -> None:
    script = _read("ops/scripts/dgx_eval_container.sh")

    assert 'for GPU_SET in "5,6,7" "0,1,2" "all"; do' in script
    assert 'docker run --rm --label project=pantherhacks --gpus "device=\\$GPU_SET"' in script


def test_train_image_is_labeled_for_cleanup_filter() -> None:
    train_script = _read("ops/scripts/dgx_train_container.sh")
    dockerfile = _read("infra/docker/trainer.Dockerfile")

    assert "--label project=pantherhacks" in train_script
    assert "LABEL project=pantherhacks" in dockerfile


def test_cli_eval_prefers_latest_checkpoint_file_when_no_in_memory_checkpoint(
    tmp_path, monkeypatch
) -> None:
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    (checkpoint_dir / "ckpt_blue_main_009.json").write_text("{}", encoding="utf-8")
    (checkpoint_dir / "ckpt_blue_main_010.json").write_text("{}", encoding="utf-8")

    replay_dir = tmp_path / "replays"
    report_dir = tmp_path / "eval_reports"

    captured: dict[str, str] = {}

    def fake_evaluate_checkpoint(
        *,
        eval_id,
        checkpoint_id,
        suite_id,
        seeds,
        replay_root,
        run_id=None,
    ):
        captured["checkpoint_id"] = checkpoint_id
        return EvalReport(
            eval_id=eval_id,
            run_id=run_id,
            suite_id=suite_id,
            kpis=EvalKpis(
                damage_reduction_vs_no_defense=0.3,
                damage_reduction_vs_rule_based=0.2,
                detection_latency_improvement_vs_rule_based=0.25,
            ),
            per_scenario=[],
        )

    monkeypatch.setattr("backend.app.cli.CHECKPOINT_DIR", checkpoint_dir)
    monkeypatch.setattr("backend.app.cli.get_active_run_id", lambda: "run_test")
    monkeypatch.setattr(
        "backend.app.cli.run_stage_dirs",
        lambda _run_id: {"train": checkpoint_dir, "replays": replay_dir, "eval": report_dir},
    )
    monkeypatch.setattr("backend.app.cli.latest_completed_checkpoint", lambda: None)
    monkeypatch.setattr("backend.app.cli.evaluate_checkpoint", fake_evaluate_checkpoint)
    monkeypatch.setattr(
        "backend.app.cli.write_eval_report",
        lambda report, output_dir: output_dir / f"{report.eval_id}.json",
    )
    monkeypatch.setattr(
        "backend.app.cli.acceptance_gate_status",
        lambda _report: {
            "damage_reduction_vs_no_defense": True,
            "damage_reduction_vs_rule_based": True,
            "detection_latency_improvement_vs_rule_based": True,
        },
    )

    _run_eval(run_id=None)

    assert captured["checkpoint_id"] == "ckpt_blue_main_010"
