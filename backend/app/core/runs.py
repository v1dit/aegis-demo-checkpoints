from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import orjson

from backend.app.core.paths import (
    CHECKPOINT_DIR,
    EVAL_REPORT_DIR,
    REPLAY_DIR,
    RUNS_DIR,
)

ACTIVE_RUN_FILE = RUNS_DIR / ".active_run"


@dataclass
class ParentInfo:
    parent_run_id: str | None
    parent_checkpoint: str | None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_dir(run_id: str) -> Path:
    return RUNS_DIR / run_id


def _manifest_path(run_id: str) -> Path:
    return _run_dir(run_id) / "manifest.json"


def _stage_dirs(run_id: str) -> dict[str, Path]:
    root = _run_dir(run_id)
    return {
        "root": root,
        "train": root / "train",
        "eval": root / "eval",
        "replays": root / "replays",
    }


def _combined_score(kpis: dict[str, float] | None) -> float:
    if not kpis:
        return -1.0
    return (
        kpis.get("damage_reduction_vs_no_defense", 0.0)
        + kpis.get("damage_reduction_vs_rule_based", 0.0)
        + kpis.get("detection_latency_improvement_vs_rule_based", 0.0)
    )


def ensure_runs_dir() -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)


def list_run_ids() -> list[str]:
    ensure_runs_dir()
    run_ids = [
        path.name
        for path in RUNS_DIR.iterdir()
        if path.is_dir() and (path / "manifest.json").exists()
    ]
    return sorted(run_ids)


def load_manifest(run_id: str) -> dict[str, Any]:
    payload = orjson.loads(_manifest_path(run_id).read_bytes())
    return payload


def save_manifest(run_id: str, manifest: dict[str, Any]) -> None:
    _manifest_path(run_id).write_bytes(
        orjson.dumps(
            manifest,
            option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS,
        )
    )


def latest_run_id() -> str | None:
    runs = list_run_ids()
    return runs[-1] if runs else None


def set_active_run_id(run_id: str) -> None:
    ensure_runs_dir()
    ACTIVE_RUN_FILE.write_text(run_id, encoding="utf-8")


def get_active_run_id() -> str | None:
    if ACTIVE_RUN_FILE.exists():
        value = ACTIVE_RUN_FILE.read_text(encoding="utf-8").strip()
        if value:
            return value
    return latest_run_id()


def resolve_best_run() -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_score = -1.0
    for run_id in list_run_ids():
        manifest = load_manifest(run_id)
        score = float(manifest.get("best_score", -1.0))
        if score > best_score:
            best = manifest
            best_score = score
    return best


def resolve_parent_info(fresh_start: bool) -> ParentInfo:
    if fresh_start:
        return ParentInfo(parent_run_id=None, parent_checkpoint=None)

    best = resolve_best_run()
    if not best:
        return ParentInfo(parent_run_id=None, parent_checkpoint=None)

    checkpoint = best.get("train", {}).get("checkpoint_id")
    run_id = best.get("run_id")
    if checkpoint and run_id:
        return ParentInfo(parent_run_id=str(run_id), parent_checkpoint=str(checkpoint))
    return ParentInfo(parent_run_id=None, parent_checkpoint=None)


def initialize_run_bundle(
    run_id: str,
    request_payload: dict[str, Any],
    parent_info: ParentInfo,
    fresh_start: bool,
) -> dict[str, Any]:
    dirs = _stage_dirs(run_id)
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "run_id": run_id,
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "fresh_start": fresh_start,
        "parent_run_id": parent_info.parent_run_id,
        "parent_checkpoint": parent_info.parent_checkpoint,
        "best_score": -1.0,
        "train": {
            "status": "queued",
            "checkpoint_id": None,
            "checkpoint_path": None,
            "request": request_payload,
            "learning_metrics": {},
        },
        "eval": {
            "status": "not_started",
            "eval_id": None,
            "report_path": None,
            "kpis": None,
            "gates": None,
            "improvement_delta_vs_parent": None,
        },
        "replays": {
            "status": "not_started",
            "replay_ids": [],
            "replay_root": str(dirs["replays"]),
        },
    }
    save_manifest(run_id, manifest)
    set_active_run_id(run_id)
    return manifest


def update_train_manifest(
    run_id: str,
    *,
    status: str,
    phase: str,
    timesteps: int,
    learning_metrics: dict[str, float],
    checkpoint_id: str | None = None,
    checkpoint_path: str | None = None,
) -> None:
    manifest = load_manifest(run_id)
    train = manifest["train"]
    train.update(
        {
            "status": status,
            "phase": phase,
            "timesteps": timesteps,
            "learning_metrics": learning_metrics,
        }
    )
    if checkpoint_id:
        train["checkpoint_id"] = checkpoint_id
    if checkpoint_path:
        train["checkpoint_path"] = checkpoint_path
    manifest["updated_at"] = _utc_now()
    save_manifest(run_id, manifest)


def update_eval_manifest(
    run_id: str,
    *,
    eval_id: str,
    status: str,
    report_path: str | None,
    kpis: dict[str, float] | None,
    gates: dict[str, bool] | None,
    improvement_delta: dict[str, float] | None,
) -> None:
    manifest = load_manifest(run_id)
    eval_data = manifest["eval"]
    eval_data.update(
        {
            "status": status,
            "eval_id": eval_id,
            "report_path": report_path,
            "kpis": kpis,
            "gates": gates,
            "improvement_delta_vs_parent": improvement_delta,
        }
    )
    manifest["best_score"] = _combined_score(kpis)
    manifest["updated_at"] = _utc_now()
    save_manifest(run_id, manifest)


def update_replay_manifest(run_id: str, replay_ids: list[str], replay_root: Path) -> None:
    manifest = load_manifest(run_id)
    manifest["replays"].update(
        {
            "status": "completed",
            "replay_ids": replay_ids,
            "replay_root": str(replay_root),
        }
    )
    manifest["updated_at"] = _utc_now()
    save_manifest(run_id, manifest)


def run_stage_dirs(run_id: str) -> dict[str, Path]:
    dirs = _stage_dirs(run_id)
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def mirror_checkpoint_to_legacy(checkpoint_file: Path, checkpoint_id: str) -> None:
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    target = CHECKPOINT_DIR / f"{checkpoint_id}.json"
    shutil.copy2(checkpoint_file, target)
    shutil.copy2(checkpoint_file, CHECKPOINT_DIR / "checkpoint_blue_demo_best.json")
    shutil.copy2(checkpoint_file, CHECKPOINT_DIR / "checkpoint_blue_demo_best")


def mirror_eval_to_legacy(eval_report_file: Path) -> None:
    EVAL_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(eval_report_file, EVAL_REPORT_DIR / eval_report_file.name)
    shutil.copy2(eval_report_file, EVAL_REPORT_DIR / "eval_report_latest.json")


def mirror_replays_to_legacy(run_replay_root: Path) -> None:
    REPLAY_DIR.mkdir(parents=True, exist_ok=True)
    for replay_dir in sorted(path for path in run_replay_root.iterdir() if path.is_dir()):
        target = REPLAY_DIR / replay_dir.name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(replay_dir, target)


def read_checkpoint_payload(checkpoint_id: str, run_id: str | None = None) -> dict[str, Any] | None:
    candidates: list[Path] = []
    if run_id:
        candidates.append(_run_dir(run_id) / "train" / f"{checkpoint_id}.json")
    active = get_active_run_id()
    if active:
        candidates.append(_run_dir(active) / "train" / f"{checkpoint_id}.json")
    candidates.append(CHECKPOINT_DIR / f"{checkpoint_id}.json")

    for path in candidates:
        if path.exists():
            return orjson.loads(path.read_bytes())
    return None


def get_parent_kpis(parent_run_id: str | None) -> dict[str, float] | None:
    if not parent_run_id:
        return None
    try:
        manifest = load_manifest(parent_run_id)
    except FileNotFoundError:
        return None
    kpis = manifest.get("eval", {}).get("kpis")
    return kpis if isinstance(kpis, dict) else None


def compute_improvement_delta(
    current_kpis: dict[str, float] | None,
    parent_kpis: dict[str, float] | None,
) -> dict[str, float] | None:
    if not current_kpis or not parent_kpis:
        return None
    keys = [
        "damage_reduction_vs_no_defense",
        "damage_reduction_vs_rule_based",
        "detection_latency_improvement_vs_rule_based",
    ]
    return {
        key: round(float(current_kpis.get(key, 0.0)) - float(parent_kpis.get(key, 0.0)), 4)
        for key in keys
    }
