from __future__ import annotations

import json
import logging

from backend.app.core.runs import get_active_run_id, resolve_canonical_run_id


def _write_manifest(runs_dir, run_id: str) -> None:
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "manifest.json").write_text(json.dumps({"run_id": run_id}), encoding="utf-8")


def test_get_active_run_id_falls_back_when_active_run_is_stale(tmp_path, monkeypatch, caplog) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    _write_manifest(runs_dir, "run_001")
    _write_manifest(runs_dir, "run_002")

    active_run_file = runs_dir / ".active_run"
    active_run_file.write_text("run_999\n", encoding="utf-8")

    monkeypatch.setattr("backend.app.core.runs.RUNS_DIR", runs_dir)
    monkeypatch.setattr("backend.app.core.runs.ACTIVE_RUN_FILE", active_run_file)

    with caplog.at_level(logging.WARNING):
        resolved = get_active_run_id()

    assert resolved == "run_002"
    assert "stale" in caplog.text.lower()


def test_resolve_canonical_run_id_prefers_latest_passing_run(tmp_path, monkeypatch) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("backend.app.core.runs.RUNS_DIR", runs_dir)
    monkeypatch.setattr("backend.app.core.runs.ACTIVE_RUN_FILE", runs_dir / ".active_run")

    incomplete = {
        "run_id": "run_001",
        "train": {"status": "completed"},
        "eval": {"status": "completed", "gates": {"damage_reduction_vs_no_defense": True}},
        "replays": {"status": "not_started"},
    }
    passing = {
        "run_id": "run_002",
        "train": {"status": "completed"},
        "eval": {
            "status": "completed",
            "gates": {
                "damage_reduction_vs_no_defense": True,
                "damage_reduction_vs_rule_based": True,
                "detection_latency_improvement_vs_rule_based": True,
            },
        },
        "replays": {"status": "completed"},
    }

    _write_manifest(runs_dir, incomplete["run_id"])
    (runs_dir / incomplete["run_id"] / "manifest.json").write_text(
        json.dumps(incomplete),
        encoding="utf-8",
    )
    _write_manifest(runs_dir, passing["run_id"])
    (runs_dir / passing["run_id"] / "manifest.json").write_text(
        json.dumps(passing),
        encoding="utf-8",
    )

    assert resolve_canonical_run_id() == passing["run_id"]
