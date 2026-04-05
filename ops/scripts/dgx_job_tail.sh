#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXEC="$ROOT_DIR/ops/scripts/cluster_exec.expect"
REMOTE_DIR_RAW="${DGX_RUNNER_DIR:-${DGX_REMOTE_DIR:-\$HOME/pantherHacks_runner}}"
JOB_ID="${1:-latest}"
TARGET_LOG="${2:-nohup.log}" # nohup.log|train.log|eval.log|package.log
LINES="${LINES:-120}"

REMOTE_CMD='
set -euo pipefail
REMOTE_DIR_RAW='"\"$REMOTE_DIR_RAW\""'
eval "REMOTE_DIR=$REMOTE_DIR_RAW"
JOB_ID='"\"$JOB_ID\""'
TARGET_LOG='"\"$TARGET_LOG\""'
LINES='"\"$LINES\""'
JOBS_ROOT="$REMOTE_DIR/.cluster_jobs"
if [ ! -d "$JOBS_ROOT" ]; then
  echo "no_jobs_found"
  exit 1
fi
if [ "$JOB_ID" = "latest" ]; then
  JOB_ID="$(ls -1 "$JOBS_ROOT" | sort | tail -n1)"
fi
JOB_DIR="$JOBS_ROOT/$JOB_ID"
if [ ! -d "$JOB_DIR" ]; then
  echo "job_not_found=$JOB_ID"
  exit 1
fi
LOG_FILE="$JOB_DIR/$TARGET_LOG"
if [ ! -f "$LOG_FILE" ]; then
  echo "log_not_found=$LOG_FILE"
  exit 1
fi
echo "job_id=$JOB_ID"
echo "log_file=$LOG_FILE"
echo "---"
tail -n "$LINES" "$LOG_FILE"
'

chmod +x "$EXEC"
"$EXEC" "$REMOTE_CMD"
