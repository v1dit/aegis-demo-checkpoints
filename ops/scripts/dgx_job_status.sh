#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXEC="$ROOT_DIR/ops/scripts/cluster_exec.expect"
REMOTE_DIR_RAW="${DGX_RUNNER_DIR:-${DGX_REMOTE_DIR:-\$HOME/pantherHacks_runner}}"
JOB_ID="${1:-latest}"

if [ "$JOB_ID" = "latest" ]; then
REMOTE_CMD='
set -euo pipefail
REMOTE_DIR_RAW='"\"$REMOTE_DIR_RAW\""'
eval "REMOTE_DIR=$REMOTE_DIR_RAW"
JOBS_ROOT="$REMOTE_DIR/.cluster_jobs"
if [ ! -d "$JOBS_ROOT" ]; then
  echo "no_jobs_found"
  exit 0
fi
LATEST_JOB="$(ls -1 "$JOBS_ROOT" | sort | tail -n1)"
if [ -z "${LATEST_JOB:-}" ]; then
  echo "no_jobs_found"
  exit 0
fi
JOB_DIR="$JOBS_ROOT/$LATEST_JOB"
echo "job_id=$LATEST_JOB"
if [ -f "$JOB_DIR/status.txt" ]; then echo "status=$(cat "$JOB_DIR/status.txt")"; fi
if [ -f "$JOB_DIR/meta.env" ]; then cat "$JOB_DIR/meta.env"; fi
if [ -f "$JOB_DIR/pid" ]; then
  PID="$(cat "$JOB_DIR/pid")"
  if ps -p "$PID" >/dev/null 2>&1; then
    echo "process=running pid=$PID"
  else
    echo "process=not_running pid=$PID"
  fi
fi
'
else
  REMOTE_CMD='
set -euo pipefail
REMOTE_DIR_RAW='"\"$REMOTE_DIR_RAW\""'
eval "REMOTE_DIR=$REMOTE_DIR_RAW"
JOB_ID='"\"$JOB_ID\""'
JOB_DIR="$REMOTE_DIR/.cluster_jobs/$JOB_ID"
if [ ! -d "$JOB_DIR" ]; then
  echo "job_not_found=$JOB_ID"
  exit 1
fi
echo "job_id=$JOB_ID"
if [ -f "$JOB_DIR/status.txt" ]; then echo "status=$(cat "$JOB_DIR/status.txt")"; fi
if [ -f "$JOB_DIR/meta.env" ]; then cat "$JOB_DIR/meta.env"; fi
if [ -f "$JOB_DIR/pid" ]; then
  PID="$(cat "$JOB_DIR/pid")"
  if ps -p "$PID" >/dev/null 2>&1; then
    echo "process=running pid=$PID"
  else
    echo "process=not_running pid=$PID"
  fi
fi
'
fi

chmod +x "$EXEC"
"$EXEC" "$REMOTE_CMD"
