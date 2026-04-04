# DGX0 No-Sudo Runbook

## 1. Connectivity
- Use `ops/scripts/cluster_ssh.expect` for interactive login.
- Use `ops/scripts/cluster_tunnel.expect` for `3000/8000/5000` local forwarding.

## 2. Preflight
- Run `ops/scripts/dgx_preflight.sh`.
- If root free space is under 250GB, do not run training jobs.

## 3. Training/Eval
- Run `ops/scripts/dgx_train_container.sh`.
- Run `ops/scripts/dgx_eval_container.sh`.

## 4. Artifact Sync
- Pull latest changes locally and copy `artifacts/` outputs as needed.

## 5. Cleanup
- Run `ops/scripts/docker_cleanup_project.sh` on the machine where containers ran.
