# DGX0 No-Sudo Runbook

## 0. Urgent Disk Constraint (DGX admin request)
- Root partition pressure is critical on `dgx0`; every PantherHacks run must clean up Docker artifacts.
- Before any heavy run, execute:
  - `ops/scripts/cluster_exec.expect 'cd $HOME/pantherHacks && bash ops/scripts/docker_cleanup_project.sh && df -h /'`
- If root free space is under 250GB after cleanup, do not launch training.

## 1. Connectivity
- Use `ops/scripts/cluster_ssh.expect` for interactive login.
- Use `ops/scripts/cluster_tunnel.expect` for `3000/8000/5000` local forwarding.

## 2. Preflight
- Run `ops/scripts/dgx_preflight.sh`.
- If root free space is under 250GB, do not run training jobs.

## 3. Training/Eval
- Run `ops/scripts/dgx_train_container.sh`.
- Run `ops/scripts/dgx_eval_container.sh`.
- For detached enterprise pipeline (recommended for long jobs):
  - Launch once: `ops/scripts/dgx_enterprise_detached.sh`
  - Launch fixed N iterations: `DGX_RUN_COUNT=8 ops/scripts/dgx_enterprise_detached.sh`
  - Launch adaptive (cap 24, plateau stop): `DGX_ADAPTIVE_MODE=1 DGX_MAX_RUNS=24 DGX_PLATEAU_REQUIRED=2 ops/scripts/dgx_enterprise_detached.sh`
  - Optional controls: `DGX_RUNNER_DIR=$HOME/pantherHacks_runner DGX_TRAIN_SEED=42 DGX_MIN_FREE_GB=250 DGX_ENTERPRISE_SUITE_ID=enterprise_suite_v1`
  - Check status later: `ops/scripts/dgx_job_status.sh [job_id|latest]`
  - Tail logs later: `ops/scripts/dgx_job_tail.sh [job_id|latest] [nohup.log|train.log|eval.log|package.log]`
  - Job exits automatically when complete and performs Docker cleanup on exit.

## 4. Artifact Sync
- Pull latest changes locally and copy `artifacts/` outputs as needed.

## 5. Cleanup
- Run `ops/scripts/docker_cleanup_project.sh` on the machine where containers ran.
