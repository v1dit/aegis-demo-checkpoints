#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXEC="$ROOT_DIR/ops/scripts/cluster_exec.expect"
REPO_URL="${DGX_REPO_URL:-https://github.com/kgarg2468/aegis.git}"
REMOTE_DIR="${DGX_REMOTE_DIR:-\$HOME/pantherHacks}"
DEFAULT_REF="$(git -C "$ROOT_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"
if [ "$DEFAULT_REF" = "HEAD" ]; then
  DEFAULT_REF="$(git -C "$ROOT_DIR" rev-parse HEAD 2>/dev/null || echo main)"
fi
TARGET_REF="${DGX_GIT_REF:-$DEFAULT_REF}"

read -r -d '' REMOTE_SCRIPT <<EOS || true
set -euo pipefail

REPO_URL="$REPO_URL"
REMOTE_DIR="$REMOTE_DIR"
TARGET_REF="$TARGET_REF"

if [ ! -d "\$REMOTE_DIR/.git" ]; then
  git clone "\$REPO_URL" "\$REMOTE_DIR"
fi

cd "\$REMOTE_DIR"
git remote set-url origin "\$REPO_URL"
git fetch origin --prune
git fetch origin "\$TARGET_REF" || true
if git show-ref --verify --quiet "refs/remotes/origin/\$TARGET_REF"; then
  git checkout -B "\$TARGET_REF" "origin/\$TARGET_REF"
else
  git checkout --detach "\$TARGET_REF"
fi

FREE_GB=\$(df --output=avail -BG / | tail -n1 | tr -dc '0-9')
if [ "\$FREE_GB" -lt 250 ]; then
  echo "Root disk free space is below 250GB. Aborting heavy run."
  exit 1
fi

docker build --label project=pantherhacks -f infra/docker/trainer.Dockerfile -t pantherhacks-trainer:latest .

for GPU_SET in "5,6,7" "0,1,2" "all"; do
  echo "Trying GPU set: \$GPU_SET"
  if [ "\$GPU_SET" = "all" ]; then
    docker run --rm --label project=pantherhacks --gpus all \
      -v "\$REMOTE_DIR/artifacts:/workspace/artifacts" \
      pantherhacks-trainer:latest && exit 0
  else
    docker run --rm --label project=pantherhacks --gpus "device=\$GPU_SET" \
      -e CUDA_VISIBLE_DEVICES="\$GPU_SET" \
      -v "\$REMOTE_DIR/artifacts:/workspace/artifacts" \
      pantherhacks-trainer:latest && exit 0
  fi
done

echo "Training container failed on all GPU fallback sets"
exit 1
EOS

chmod +x "$EXEC"
"$EXEC" "$REMOTE_SCRIPT"
