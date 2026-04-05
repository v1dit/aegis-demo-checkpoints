#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CLUSTER_EXEC="$ROOT_DIR/ops/scripts/cluster_exec.expect"
PASSES="${CLUSTER_VALIDATION_PASSES:-3}"
BASE_HTTP_URL="${BASE_HTTP_URL:-http://127.0.0.1:8000}"
BASE_WS_URL="${BASE_WS_URL:-ws://127.0.0.1:8000}"
EVIDENCE_ROOT="${CLUSTER_VALIDATION_EVIDENCE_ROOT:-$ROOT_DIR/artifacts/cluster_validation}"
TIMESTAMP="$(date -u +%Y%m%d_%H%M%S)"
RUN_DIR="$EVIDENCE_ROOT/$TIMESTAMP"
REMOTE_DIR_RAW="${DGX_RUNNER_DIR:-${DGX_REMOTE_DIR:-\$HOME/pantherHacks_runner}}"

mkdir -p "$RUN_DIR"
chmod +x "$CLUSTER_EXEC"

for cmd in uv curl; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "missing required command: $cmd" >&2
    exit 1
  fi
done

if ! [[ "$PASSES" =~ ^[1-9][0-9]*$ ]]; then
  echo "CLUSTER_VALIDATION_PASSES must be a positive integer. Got: $PASSES" >&2
  exit 1
fi

LOCAL_BRANCH="$(git -C "$ROOT_DIR" rev-parse --abbrev-ref HEAD)"
LOCAL_SHA="$(git -C "$ROOT_DIR" rev-parse HEAD)"

REMOTE_META_CMD=$(cat <<'EOS'
set -euo pipefail
REMOTE_DIR_RAW="__REMOTE_DIR_RAW__"
eval "REMOTE_DIR=$REMOTE_DIR_RAW"
if [ ! -d "$REMOTE_DIR/.git" ]; then
  echo "remote_repo_missing=$REMOTE_DIR"
  exit 1
fi
cd "$REMOTE_DIR"
echo "remote_branch=$(git rev-parse --abbrev-ref HEAD)"
echo "remote_sha=$(git rev-parse HEAD)"
EOS
)
REMOTE_META_CMD="${REMOTE_META_CMD//__REMOTE_DIR_RAW__/$REMOTE_DIR_RAW}"

REMOTE_METADATA_LOG="$RUN_DIR/remote_metadata.log"
if ! "$CLUSTER_EXEC" "$REMOTE_META_CMD" >"$REMOTE_METADATA_LOG" 2>&1; then
  cat "$REMOTE_METADATA_LOG" >&2 || true
  echo "failed to fetch remote metadata via cluster_exec.expect" >&2
  exit 1
fi

REMOTE_BRANCH="$(grep -E '^remote_branch=' "$REMOTE_METADATA_LOG" | tail -n1 | cut -d= -f2- || true)"
REMOTE_SHA="$(grep -E '^remote_sha=' "$REMOTE_METADATA_LOG" | tail -n1 | cut -d= -f2- || true)"

cat >"$RUN_DIR/metadata.json" <<EOF
{
  "started_at_utc": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "passes_required": $PASSES,
  "base_http_url": "$BASE_HTTP_URL",
  "base_ws_url": "$BASE_WS_URL",
  "local_branch": "$LOCAL_BRANCH",
  "local_sha": "$LOCAL_SHA",
  "remote_branch": "$REMOTE_BRANCH",
  "remote_sha": "$REMOTE_SHA",
  "remote_runner_dir_raw": "$REMOTE_DIR_RAW"
}
EOF

echo "Preflight: health/catalog reachability check"
HEALTH_CODE="$(curl -sS -o "$RUN_DIR/health_raw.json" -w "%{http_code}" "$BASE_HTTP_URL/health" || true)"
if [ "$HEALTH_CODE" = "200" ]; then
  cp "$RUN_DIR/health_raw.json" "$RUN_DIR/health.json"
  echo "health_check=ok" | tee "$RUN_DIR/preflight_status.log" >/dev/null
else
  echo "health_check=unavailable code=$HEALTH_CODE (falling back to /sandbox/catalog)" | tee "$RUN_DIR/preflight_status.log"
  curl -fsS "$BASE_HTTP_URL/sandbox/catalog" > "$RUN_DIR/catalog_preflight.json"
fi

echo "BUG-001 pre-check: uv run pytest -q"
uv run pytest -q | tee "$RUN_DIR/pytest_full.log"

run_bug002_probe() {
  local pass_dir="$1"
  local probe_log="$pass_dir/bug002_probe.log"
  local remote_prepare_cmd
  remote_prepare_cmd=$(cat <<'EOS'
set -euo pipefail
REMOTE_DIR_RAW="__REMOTE_DIR_RAW__"
eval "REMOTE_DIR=$REMOTE_DIR_RAW"

mkdir -p "$REMOTE_DIR"
docker run --rm -v "$REMOTE_DIR:/workspace" busybox:1.36 sh -c \
  'mkdir -p /workspace/artifacts/replays/probe /workspace/runs/probe && touch /workspace/artifacts/replays/probe/root_owned.txt /workspace/runs/probe/root_owned.txt'
echo "prepare_status=ok"
EOS
)
  remote_prepare_cmd="${remote_prepare_cmd//__REMOTE_DIR_RAW__/$REMOTE_DIR_RAW}"

  if ! "$CLUSTER_EXEC" "$remote_prepare_cmd" | tee "$probe_log"; then
    return 1
  fi
  if ! grep -q "prepare_status=ok" "$probe_log"; then
    return 1
  fi

  local dgx_force_clean_log="$pass_dir/bug002_force_clean.log"
  if ! DGX_RUNNER_DIR="$REMOTE_DIR_RAW" \
    DGX_FORCE_CLEAN_RUNNER=1 \
    DGX_RUN_COUNT=1 \
    DGX_ADAPTIVE_MODE=0 \
    DGX_MIN_FREE_GB=1 \
    "$ROOT_DIR/ops/scripts/dgx_enterprise_detached.sh" >"$dgx_force_clean_log" 2>&1; then
    cat "$dgx_force_clean_log" >&2 || true
    return 1
  fi
  if grep -qi "permission denied" "$dgx_force_clean_log"; then
    return 1
  fi

  local remote_verify_cmd
  remote_verify_cmd=$(cat <<'EOS'
set -euo pipefail
REMOTE_DIR_RAW="__REMOTE_DIR_RAW__"
eval "REMOTE_DIR=$REMOTE_DIR_RAW"
EXPECTED_OWNER="$(id -un):$(id -gn)"
HOST_UID="$(id -u)"
HOST_GID="$(id -g)"
ART_MOUNT="${REMOTE_DIR}/artifacts:/workspace/artifacts"
RUN_MOUNT="${REMOTE_DIR}/runs:/workspace/runs"

docker run --rm --user "${HOST_UID}:${HOST_GID}" -v "${ART_MOUNT}" busybox:1.36 sh -c \
  'mkdir -p /workspace/artifacts/replays/probe && touch /workspace/artifacts/replays/probe/owner_probe.txt'
docker run --rm --user "${HOST_UID}:${HOST_GID}" -v "${RUN_MOUNT}" busybox:1.36 sh -c \
  'mkdir -p /workspace/runs/probe && touch /workspace/runs/probe/owner_probe.txt'

ART_OWNER="$(stat -c "%U:%G" "$REMOTE_DIR/artifacts/replays/probe/owner_probe.txt")"
RUN_OWNER="$(stat -c "%U:%G" "$REMOTE_DIR/runs/probe/owner_probe.txt")"
echo "expected_owner=$EXPECTED_OWNER"
echo "art_owner=$ART_OWNER"
echo "run_owner=$RUN_OWNER"
if [ "$ART_OWNER" != "$EXPECTED_OWNER" ] || [ "$RUN_OWNER" != "$EXPECTED_OWNER" ]; then
  echo "probe_failed=owner_mismatch"
  exit 1
fi

echo "probe_status=ok"
EOS
)
  remote_verify_cmd="${remote_verify_cmd//__REMOTE_DIR_RAW__/$REMOTE_DIR_RAW}"

  if ! "$CLUSTER_EXEC" "$remote_verify_cmd" | tee -a "$probe_log"; then
    return 1
  fi
  if grep -qi "permission denied" "$probe_log"; then
    return 1
  fi
  if ! grep -q "probe_status=ok" "$probe_log"; then
    return 1
  fi
}

ensure_remote_api_up() {
  local pass_dir="$1"
  local api_bootstrap_log="$pass_dir/api_bootstrap.log"
  local remote_bootstrap_cmd
  remote_bootstrap_cmd=$(cat <<'EOS'
set -euo pipefail
REMOTE_DIR_RAW="__REMOTE_DIR_RAW__"
eval "REMOTE_DIR=$REMOTE_DIR_RAW"
cd "$REMOTE_DIR"
if ! docker image inspect pantherhacks-trainer:latest >/dev/null 2>&1; then
  docker build --label project=pantherhacks -f infra/docker/trainer.Dockerfile -t pantherhacks-trainer:latest .
fi
docker rm -f pantherhacks-sandbox-api >/dev/null 2>&1 || true
docker run -d --name pantherhacks-sandbox-api --label project=pantherhacks -p 8000:8000 \
  -e SANDBOX_EXECUTION_MODE=cluster \
  -e SANDBOX_CHECKPOINT_ID=checkpoint_blue_demo_best \
  -v "$REMOTE_DIR/artifacts:/workspace/artifacts" \
  -v "$REMOTE_DIR/runs:/workspace/runs" \
  pantherhacks-trainer:latest uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 >/dev/null
sleep 3
curl -sS -m 20 http://127.0.0.1:8000/sandbox/catalog
echo
echo "api_bootstrap_status=ok"
EOS
)
  remote_bootstrap_cmd="${remote_bootstrap_cmd//__REMOTE_DIR_RAW__/$REMOTE_DIR_RAW}"
  if ! "$CLUSTER_EXEC" "$remote_bootstrap_cmd" | tee "$api_bootstrap_log"; then
    return 1
  fi
  if ! grep -q "api_bootstrap_status=ok" "$api_bootstrap_log"; then
    return 1
  fi
}

wait_for_local_api() {
  local attempts=30
  local sleep_s=2
  local i
  for i in $(seq 1 "$attempts"); do
    if curl -fsS -m 10 "$BASE_HTTP_URL/sandbox/catalog" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$sleep_s"
  done
  return 1
}

for pass_index in $(seq 1 "$PASSES"); do
  echo "Starting pass ${pass_index}/${PASSES}"
  PASS_DIR="$RUN_DIR/pass_${pass_index}"
  mkdir -p "$PASS_DIR"

  echo "BUG-002 probe: pass ${pass_index}/${PASSES}"
  if ! run_bug002_probe "$PASS_DIR"; then
    echo "BUG-002 probe failed on pass ${pass_index}" >&2
    exit 1
  fi

  echo "Ensuring remote API is running: pass ${pass_index}/${PASSES}"
  if ! ensure_remote_api_up "$PASS_DIR"; then
    echo "remote API bootstrap failed on pass ${pass_index}" >&2
    exit 1
  fi
  if ! wait_for_local_api; then
    echo "local API reachability check failed after remote bootstrap on pass ${pass_index}" >&2
    exit 1
  fi

  echo "Live cluster contract test: pass ${pass_index}/${PASSES}"
  RUN_CLUSTER_TESTS=1 \
  BASE_HTTP_URL="$BASE_HTTP_URL" \
  BASE_WS_URL="$BASE_WS_URL" \
  CLUSTER_VALIDATION_EVIDENCE_DIR="$PASS_DIR" \
  uv run pytest tests/cluster/test_sandbox_contract_live.py -q | tee "$PASS_DIR/cluster_contract.log"
done

cat >"$RUN_DIR/final_status.json" <<EOF
{
  "finished_at_utc": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "result": "PASS",
  "passes_completed": $PASSES
}
EOF

echo "Cluster sandbox contract gate passed. Evidence: $RUN_DIR"
