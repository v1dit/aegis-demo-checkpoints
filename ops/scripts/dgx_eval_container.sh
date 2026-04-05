#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXEC="$ROOT_DIR/ops/scripts/cluster_exec.expect"
REMOTE_DIR="${DGX_REMOTE_DIR:-\$HOME/pantherHacks}"

read -r -d '' REMOTE_SCRIPT <<EOS || true
set -euo pipefail

REMOTE_DIR="$REMOTE_DIR"
cd "\$REMOTE_DIR"

if ! docker image inspect pantherhacks-trainer:latest >/dev/null 2>&1; then
  echo "pantherhacks-trainer:latest not found. Run dgx_train_container.sh first."
  exit 1
fi

HOST_UID="\$(id -u)"
HOST_GID="\$(id -g)"

for GPU_SET in "5,6,7" "0,1,2" "all"; do
  echo "Trying GPU set: \$GPU_SET"
  if [ "\$GPU_SET" = "all" ]; then
    docker run --rm --label project=pantherhacks --gpus all --user "\$HOST_UID:\$HOST_GID" \
      -v "\$REMOTE_DIR/artifacts:/workspace/artifacts" \
      pantherhacks-trainer:latest python -m backend.app.cli eval && exit 0
  else
    docker run --rm --label project=pantherhacks --gpus "device=\$GPU_SET" --user "\$HOST_UID:\$HOST_GID" \
      -e CUDA_VISIBLE_DEVICES="\$GPU_SET" \
      -v "\$REMOTE_DIR/artifacts:/workspace/artifacts" \
      pantherhacks-trainer:latest python -m backend.app.cli eval && exit 0
  fi
done

echo "Eval container failed on all GPU fallback sets"
exit 1
EOS

chmod +x "$EXEC"
"$EXEC" "$REMOTE_SCRIPT"
