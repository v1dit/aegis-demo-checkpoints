#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXEC="$ROOT_DIR/ops/scripts/cluster_exec.expect"
REPO_URL="${DGX_REPO_URL:-https://github.com/kgarg2468/aegis.git}"
REMOTE_DIR="${DGX_RUNNER_DIR:-${DGX_REMOTE_DIR:-\$HOME/pantherHacks_runner}}"
DEFAULT_REF="$(git -C "$ROOT_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"
if [ "$DEFAULT_REF" = "HEAD" ]; then
  DEFAULT_REF="$(git -C "$ROOT_DIR" rev-parse HEAD 2>/dev/null || echo main)"
fi
TARGET_REF="${DGX_GIT_REF:-$DEFAULT_REF}"
TRAIN_SEED="${DGX_TRAIN_SEED:-42}"
RUN_COUNT="${DGX_RUN_COUNT:-1}"
ADAPTIVE_MODE="${DGX_ADAPTIVE_MODE:-0}"
MAX_RUNS="${DGX_MAX_RUNS:-24}"
PLATEAU_REQUIRED="${DGX_PLATEAU_REQUIRED:-2}"
PLATEAU_EPS="${DGX_PLATEAU_EPS:-0.01}"
FORCE_CLEAN_RUNNER="${DGX_FORCE_CLEAN_RUNNER:-0}"
ENTERPRISE_SCENARIO="${DGX_ENTERPRISE_SCENARIO_ID:-scenario_enterprise_crm_identity_chain_v1}"
ENTERPRISE_SUITE="${DGX_ENTERPRISE_SUITE_ID:-enterprise_suite_v1}"
EVAL_SEEDS="${DGX_EVAL_SEEDS:-2001,2002,2003,2004}"
MIN_FREE_GB="${DGX_MIN_FREE_GB:-250}"

if ! [[ "$RUN_COUNT" =~ ^[1-9][0-9]*$ ]]; then
  echo "DGX_RUN_COUNT must be a positive integer. Got: $RUN_COUNT" >&2
  exit 1
fi
if ! [[ "$MAX_RUNS" =~ ^[1-9][0-9]*$ ]]; then
  echo "DGX_MAX_RUNS must be a positive integer. Got: $MAX_RUNS" >&2
  exit 1
fi
if ! [[ "$PLATEAU_REQUIRED" =~ ^[1-9][0-9]*$ ]]; then
  echo "DGX_PLATEAU_REQUIRED must be a positive integer. Got: $PLATEAU_REQUIRED" >&2
  exit 1
fi
if ! [[ "$ADAPTIVE_MODE" =~ ^[01]$ ]]; then
  echo "DGX_ADAPTIVE_MODE must be 0 or 1. Got: $ADAPTIVE_MODE" >&2
  exit 1
fi
if ! [[ "$FORCE_CLEAN_RUNNER" =~ ^[01]$ ]]; then
  echo "DGX_FORCE_CLEAN_RUNNER must be 0 or 1. Got: $FORCE_CLEAN_RUNNER" >&2
  exit 1
fi

REMOTE_SCRIPT_TEMPLATE=$(cat <<'EOS'
set -euo pipefail

REPO_URL="__REPO_URL__"
REMOTE_DIR="__REMOTE_DIR__"
TARGET_REF="__TARGET_REF__"
TRAIN_SEED="__TRAIN_SEED__"
RUN_COUNT="__RUN_COUNT__"
ADAPTIVE_MODE="__ADAPTIVE_MODE__"
MAX_RUNS="__MAX_RUNS__"
PLATEAU_REQUIRED="__PLATEAU_REQUIRED__"
PLATEAU_EPS="__PLATEAU_EPS__"
FORCE_CLEAN_RUNNER="__FORCE_CLEAN_RUNNER__"
ENTERPRISE_SCENARIO="__ENTERPRISE_SCENARIO__"
ENTERPRISE_SUITE="__ENTERPRISE_SUITE__"
EVAL_SEEDS="__EVAL_SEEDS__"
MIN_FREE_GB="__MIN_FREE_GB__"
HOST_UID="$(id -u)"
HOST_GID="$(id -g)"

root_free_gb() {
  df --output=avail -BG / | tail -n1 | tr -dc '0-9'
}

cleanup_project_docker() {
  docker ps -a --filter "label=project=pantherhacks" -q | xargs -r docker rm -f >/dev/null 2>&1 || true
  docker images --filter "label=project=pantherhacks" -q | xargs -r docker rmi -f >/dev/null 2>&1 || true
  docker images "pantherhacks-*" -q | xargs -r docker rmi -f >/dev/null 2>&1 || true
  docker volume ls --filter "label=project=pantherhacks" -q | xargs -r docker volume rm >/dev/null 2>&1 || true
  docker builder prune -af >/dev/null 2>&1 || true
  docker image prune -f >/dev/null 2>&1 || true
}

repair_runner_permissions() {
  local target_dir="$1"
  local repair_image="pantherhacks-trainer:latest"
  if ! docker image inspect "$repair_image" >/dev/null 2>&1; then
    repair_image="busybox:1.36"
  fi
  echo "repairing_runner_permissions dir=$target_dir image=$repair_image"
  if ! docker run --rm -v "$target_dir:/workspace" "$repair_image" sh -c \
    "set -eu; [ -e /workspace/artifacts ] && chown -R $HOST_UID:$HOST_GID /workspace/artifacts || true; [ -e /workspace/runs ] && chown -R $HOST_UID:$HOST_GID /workspace/runs || true"; then
    echo "permission_repair_failed dir=$target_dir image=$repair_image"
    return 1
  fi
}

ensure_root_free() {
  local free_gb
  free_gb="$(root_free_gb)"
  if [ "$free_gb" -lt "$MIN_FREE_GB" ]; then
    echo "Root disk free space is ${free_gb}GB (< ${MIN_FREE_GB}GB). Aborting run."
    exit 1
  fi
}

if [ "$FORCE_CLEAN_RUNNER" = "1" ] && [ -d "$REMOTE_DIR" ]; then
  if ! repair_runner_permissions "$REMOTE_DIR"; then
    echo "failed:runner_cleanup_permission_denied"
    echo "hint=unable_to_repair_ownership_before_cleanup"
    exit 1
  fi
  if ! rm -rf "$REMOTE_DIR"; then
    echo "failed:runner_cleanup_permission_denied"
    echo "hint=rm_rf_failed_after_permission_repair"
    exit 1
  fi
  if [ -d "$REMOTE_DIR" ]; then
    echo "failed:runner_cleanup_permission_denied"
    echo "hint=runner_dir_still_exists_after_cleanup"
    exit 1
  fi
fi

if [ ! -d "$REMOTE_DIR/.git" ]; then
  git clone "$REPO_URL" "$REMOTE_DIR"
fi

cd "$REMOTE_DIR"
git remote set-url origin "$REPO_URL"
git fetch origin --prune
git fetch origin "$TARGET_REF" || true
if git show-ref --verify --quiet "refs/remotes/origin/$TARGET_REF"; then
  git checkout -B "$TARGET_REF" "origin/$TARGET_REF"
  git reset --hard "origin/$TARGET_REF"
else
  git checkout --detach "$TARGET_REF"
fi
git clean -fdx >/dev/null 2>&1 || true

cleanup_project_docker
ensure_root_free

mkdir -p "$REMOTE_DIR/artifacts" "$REMOTE_DIR/runs" "$REMOTE_DIR/.cluster_jobs"
docker build --label project=pantherhacks -f infra/docker/trainer.Dockerfile -t pantherhacks-trainer:latest .
ensure_root_free

JOB_ID="enterprise_$(date +%Y%m%d_%H%M%S)"
JOB_DIR="$REMOTE_DIR/.cluster_jobs/$JOB_ID"
JOB_SCRIPT="$JOB_DIR/job.sh"
mkdir -p "$JOB_DIR"

cat > "$JOB_SCRIPT" <<'EOF_JOB'
#!/usr/bin/env bash
set -euo pipefail

REMOTE_DIR="${REMOTE_DIR:?}"
TRAIN_SEED="${TRAIN_SEED:?}"
RUN_COUNT="${RUN_COUNT:?}"
ADAPTIVE_MODE="${ADAPTIVE_MODE:?}"
MAX_RUNS="${MAX_RUNS:?}"
PLATEAU_REQUIRED="${PLATEAU_REQUIRED:?}"
PLATEAU_EPS="${PLATEAU_EPS:?}"
ENTERPRISE_SCENARIO="${ENTERPRISE_SCENARIO:?}"
ENTERPRISE_SUITE="${ENTERPRISE_SUITE:?}"
EVAL_SEEDS="${EVAL_SEEDS:?}"
MIN_FREE_GB="${MIN_FREE_GB:?}"
JOB_DIR="${JOB_DIR:?}"

STATUS_FILE="$JOB_DIR/status.txt"
TRAIN_LOG="$JOB_DIR/train.log"
EVAL_LOG="$JOB_DIR/eval.log"
PKG_LOG="$JOB_DIR/package.log"
META_FILE="$JOB_DIR/meta.env"

echo "running" > "$STATUS_FILE"
HOST_UID="$(id -u)"
HOST_GID="$(id -g)"

root_free_gb() {
  df --output=avail -BG / | tail -n1 | tr -dc '0-9'
}

cleanup_project_docker() {
  docker ps -a --filter "label=project=pantherhacks" -q | xargs -r docker rm -f >/dev/null 2>&1 || true
  docker images --filter "label=project=pantherhacks" -q | xargs -r docker rmi -f >/dev/null 2>&1 || true
  docker images "pantherhacks-*" -q | xargs -r docker rmi -f >/dev/null 2>&1 || true
  docker volume ls --filter "label=project=pantherhacks" -q | xargs -r docker volume rm >/dev/null 2>&1 || true
  docker builder prune -af >/dev/null 2>&1 || true
  docker image prune -f >/dev/null 2>&1 || true
}

ensure_root_free() {
  local free_gb
  free_gb="$(root_free_gb)"
  if [ "$free_gb" -lt "$MIN_FREE_GB" ]; then
    echo "failed:root_space" > "$STATUS_FILE"
    echo "root_free_gb=${free_gb}" >> "$META_FILE"
    exit 1
  fi
}

on_exit() {
  cleanup_project_docker
  {
    echo "---"
    echo "docker_system_df=$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    docker system df || true
  } >> "$JOB_DIR/nohup.log" 2>&1
}

trap on_exit EXIT

run_container() {
  local task_name="$1"
  local command="$2"
  local log_file="$3"
  local gpu_set
  for gpu_set in "5,6,7" "0,1,2" "all"; do
    echo "[${task_name}] trying GPU set: ${gpu_set}" | tee -a "$log_file"
    if docker run --rm --label project=pantherhacks --gpus all --user "$HOST_UID:$HOST_GID" \
      -e CUDA_VISIBLE_DEVICES="$gpu_set" \
      -e PPO_SCENARIO_ID="$ENTERPRISE_SCENARIO" \
      -e PPO_EVAL_SUITE_ID="$ENTERPRISE_SUITE" \
      -e PPO_EVAL_SEEDS="$EVAL_SEEDS" \
      -v "$REMOTE_DIR/artifacts:/workspace/artifacts" \
      -v "$REMOTE_DIR/runs:/workspace/runs" \
      pantherhacks-trainer:latest bash -lc "$command" >>"$log_file" 2>&1; then
      return 0
    fi
  done
  return 1
}

run_train_with_fallback() {
  local iter="$1"
  local seed="$2"
  local commands=()
  commands+=("python -m backend.app.cli --fresh-start --seed ${seed} train")
  commands+=("python -m backend.app.cli --fresh-start train --seed ${seed}")
  commands+=("python -m backend.app.cli --fresh-start train")
  commands+=("PPO_REQUIRE_PREFLIGHT_GATE=false python -m backend.app.cli --fresh-start --seed ${seed} train")
  commands+=("PPO_REQUIRE_PREFLIGHT_GATE=false python -m backend.app.cli --fresh-start train --seed ${seed}")
  commands+=("PPO_REQUIRE_PREFLIGHT_GATE=false python -m backend.app.cli --fresh-start train")
  commands+=("python -m backend.app.cli train")
  local cmd
  for cmd in "${commands[@]}"; do
    if run_container "train#${iter}" "$cmd" "$TRAIN_LOG"; then
      status_now="$(latest_train_status)"
      if [ "$status_now" = "completed" ]; then
        return 0
      fi
      echo "[train#${iter}] command finished but train status=${status_now}; trying next fallback" | tee -a "$TRAIN_LOG"
    fi
  done
  return 1
}

run_eval_with_fallback() {
  local iter="$1"
  local run_id="$2"
  local commands=()
  commands+=("python -m backend.app.cli --run-id ${run_id} --suite-id ${ENTERPRISE_SUITE} --eval-seeds ${EVAL_SEEDS} eval")
  commands+=("python -m backend.app.cli eval --run-id ${run_id} --suite-id ${ENTERPRISE_SUITE} --eval-seeds ${EVAL_SEEDS}")
  commands+=("python -m backend.app.cli --run-id ${run_id} eval")
  commands+=("python -m backend.app.cli eval --run-id ${run_id}")
  commands+=("python -m backend.app.cli eval")
  local cmd
  for cmd in "${commands[@]}"; do
    if run_container "enterprise_eval#${iter}" "$cmd" "$EVAL_LOG"; then
      return 0
    fi
  done
  return 1
}

run_package_with_fallback() {
  local iter="$1"
  local run_id="$2"
  local commands=()
  commands+=("python -m backend.app.cli --run-id ${run_id} package-replays")
  commands+=("python -m backend.app.cli package-replays --run-id ${run_id}")
  commands+=("python -m backend.app.cli package-replays")
  local cmd
  for cmd in "${commands[@]}"; do
    if run_container "package_replays#${iter}" "$cmd" "$PKG_LOG"; then
      return 0
    fi
  done
  return 1
}

extract_kpi_primary() {
  grep -E "kpis=" "$EVAL_LOG" | tail -n1 \
    | grep -Eo "damage_reduction_vs_no_defense['\"]?:[[:space:]]*-?[0-9]+(\.[0-9]+)?" \
    | grep -Eo "-?[0-9]+(\.[0-9]+)?" \
    | tail -n1 || true
}

latest_train_status() {
  grep -Eo 'status=[a-z_]+' "$TRAIN_LOG" | tail -n1 | cut -d= -f2 || true
}

extract_eval_report_path() {
  local raw
  raw="$(grep -Eo 'eval_report=[^ ]+' "$EVAL_LOG" | tail -n1 | cut -d= -f2- || true)"
  if [ -z "$raw" ]; then
    echo ""
    return
  fi
  if [[ "$raw" == /workspace/* ]]; then
    echo "$REMOTE_DIR/${raw#/workspace/}"
  else
    echo "$raw"
  fi
}

is_significant_improvement() {
  local current="$1"
  local best="$2"
  local eps="$3"
  awk -v cur="$current" -v bst="$best" -v e="$eps" 'BEGIN { if ((cur - bst) > e) print "1"; else print "0" }'
}

if [ "$ADAPTIVE_MODE" = "1" ]; then
  TARGET_ITERATIONS="$MAX_RUNS"
else
  TARGET_ITERATIONS="$RUN_COUNT"
fi

{
  echo "job_dir=$JOB_DIR"
  echo "started_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  echo "enterprise_scenario=$ENTERPRISE_SCENARIO"
  echo "enterprise_suite=$ENTERPRISE_SUITE"
  echo "base_train_seed=$TRAIN_SEED"
  echo "eval_seeds=$EVAL_SEEDS"
  echo "adaptive_mode=$ADAPTIVE_MODE"
  echo "requested_run_count=$RUN_COUNT"
  echo "max_runs=$MAX_RUNS"
  echo "target_iterations=$TARGET_ITERATIONS"
  echo "plateau_required=$PLATEAU_REQUIRED"
  echo "plateau_eps=$PLATEAU_EPS"
} > "$META_FILE"

ensure_root_free

BEST_KPI=""
PLATEAU_COUNT=0
COMPLETED_ITERATIONS=0

for ((iter = 1; iter <= TARGET_ITERATIONS; iter++)); do
  run_seed=$((TRAIN_SEED + iter - 1))
  echo "=== iteration ${iter}/${TARGET_ITERATIONS} seed=${run_seed} ===" | tee -a "$TRAIN_LOG" "$EVAL_LOG" "$PKG_LOG"

  if ! run_train_with_fallback "$iter" "$run_seed"; then
    echo "failed:train:iter_${iter}" > "$STATUS_FILE"
    exit 1
  fi

  RUN_ID="$(grep -Eo 'run_id=[^ ]+' "$TRAIN_LOG" | tail -n1 | cut -d= -f2)"
  if [ -z "${RUN_ID:-}" ]; then
    echo "failed:run_id_parse:iter_${iter}" > "$STATUS_FILE"
    exit 1
  fi
  echo "iter_${iter}_run_id=$RUN_ID" >> "$META_FILE"

  if ! run_eval_with_fallback "$iter" "$RUN_ID"; then
    echo "failed:enterprise_eval:iter_${iter}" > "$STATUS_FILE"
    exit 1
  fi

  EVAL_REPORT_PATH="$(extract_eval_report_path)"
  if [ -n "$EVAL_REPORT_PATH" ]; then
    echo "iter_${iter}_eval_report=$EVAL_REPORT_PATH" >> "$META_FILE"
  fi

  KPI_PRIMARY="$(extract_kpi_primary)"
  if [ -n "$KPI_PRIMARY" ]; then
    echo "iter_${iter}_kpi_damage_reduction_vs_no_defense=$KPI_PRIMARY" >> "$META_FILE"
    if [ -z "$BEST_KPI" ]; then
      BEST_KPI="$KPI_PRIMARY"
      PLATEAU_COUNT=0
    else
      if [ "$(is_significant_improvement "$KPI_PRIMARY" "$BEST_KPI" "$PLATEAU_EPS")" = "1" ]; then
        BEST_KPI="$KPI_PRIMARY"
        PLATEAU_COUNT=0
      else
        PLATEAU_COUNT=$((PLATEAU_COUNT + 1))
      fi
    fi
    echo "iter_${iter}_best_kpi_damage_reduction_vs_no_defense=$BEST_KPI" >> "$META_FILE"
    echo "iter_${iter}_plateau_count=$PLATEAU_COUNT" >> "$META_FILE"
  fi

  if ! run_package_with_fallback "$iter" "$RUN_ID"; then
    echo "failed:package_replays:iter_${iter}" > "$STATUS_FILE"
    exit 1
  fi

  ensure_root_free
  COMPLETED_ITERATIONS="$iter"
  echo "iter_${iter}_status=completed" >> "$META_FILE"

  if [ "$ADAPTIVE_MODE" = "1" ] && [ "$PLATEAU_COUNT" -ge "$PLATEAU_REQUIRED" ]; then
    echo "adaptive_stop_iter=$iter" >> "$META_FILE"
    echo "adaptive_stop_reason=plateau_${PLATEAU_REQUIRED}" >> "$META_FILE"
    break
  fi
done

{
  echo "completed_iterations=$COMPLETED_ITERATIONS"
  echo "completed_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  echo "status=completed"
} >> "$META_FILE"
echo "completed" > "$STATUS_FILE"
EOF_JOB

chmod +x "$JOB_SCRIPT"
nohup env \
  REMOTE_DIR="$REMOTE_DIR" \
  TRAIN_SEED="$TRAIN_SEED" \
  RUN_COUNT="$RUN_COUNT" \
  ADAPTIVE_MODE="$ADAPTIVE_MODE" \
  MAX_RUNS="$MAX_RUNS" \
  PLATEAU_REQUIRED="$PLATEAU_REQUIRED" \
  PLATEAU_EPS="$PLATEAU_EPS" \
  ENTERPRISE_SCENARIO="$ENTERPRISE_SCENARIO" \
  ENTERPRISE_SUITE="$ENTERPRISE_SUITE" \
  EVAL_SEEDS="$EVAL_SEEDS" \
  MIN_FREE_GB="$MIN_FREE_GB" \
  JOB_DIR="$JOB_DIR" \
  bash "$JOB_SCRIPT" > "$JOB_DIR/nohup.log" 2>&1 < /dev/null &
PID=$!
echo "$PID" > "$JOB_DIR/pid"

echo "job_id=$JOB_ID"
echo "job_dir=$JOB_DIR"
echo "pid=$PID"
echo "status_file=$JOB_DIR/status.txt"
echo "adaptive_mode=$ADAPTIVE_MODE"
echo "target_iterations=$([ "$ADAPTIVE_MODE" = "1" ] && echo "$MAX_RUNS" || echo "$RUN_COUNT")"
EOS
)

REMOTE_SCRIPT="${REMOTE_SCRIPT_TEMPLATE//__REPO_URL__/$REPO_URL}"
REMOTE_SCRIPT="${REMOTE_SCRIPT//__REMOTE_DIR__/$REMOTE_DIR}"
REMOTE_SCRIPT="${REMOTE_SCRIPT//__TARGET_REF__/$TARGET_REF}"
REMOTE_SCRIPT="${REMOTE_SCRIPT//__TRAIN_SEED__/$TRAIN_SEED}"
REMOTE_SCRIPT="${REMOTE_SCRIPT//__RUN_COUNT__/$RUN_COUNT}"
REMOTE_SCRIPT="${REMOTE_SCRIPT//__ADAPTIVE_MODE__/$ADAPTIVE_MODE}"
REMOTE_SCRIPT="${REMOTE_SCRIPT//__MAX_RUNS__/$MAX_RUNS}"
REMOTE_SCRIPT="${REMOTE_SCRIPT//__PLATEAU_REQUIRED__/$PLATEAU_REQUIRED}"
REMOTE_SCRIPT="${REMOTE_SCRIPT//__PLATEAU_EPS__/$PLATEAU_EPS}"
REMOTE_SCRIPT="${REMOTE_SCRIPT//__FORCE_CLEAN_RUNNER__/$FORCE_CLEAN_RUNNER}"
REMOTE_SCRIPT="${REMOTE_SCRIPT//__ENTERPRISE_SCENARIO__/$ENTERPRISE_SCENARIO}"
REMOTE_SCRIPT="${REMOTE_SCRIPT//__ENTERPRISE_SUITE__/$ENTERPRISE_SUITE}"
REMOTE_SCRIPT="${REMOTE_SCRIPT//__EVAL_SEEDS__/$EVAL_SEEDS}"
REMOTE_SCRIPT="${REMOTE_SCRIPT//__MIN_FREE_GB__/$MIN_FREE_GB}"

chmod +x "$EXEC"
"$EXEC" "$REMOTE_SCRIPT"
