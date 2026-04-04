from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS_DIR = REPO_ROOT / "artifacts"
CHECKPOINT_DIR = ARTIFACTS_DIR / "checkpoints"
REPLAY_DIR = ARTIFACTS_DIR / "replays"
EVAL_REPORT_DIR = ARTIFACTS_DIR / "eval_reports"
FIXTURES_DIR = ARTIFACTS_DIR / "fixtures"


def ensure_artifact_dirs() -> None:
    for path in [CHECKPOINT_DIR, REPLAY_DIR, EVAL_REPORT_DIR, FIXTURES_DIR]:
        path.mkdir(parents=True, exist_ok=True)
