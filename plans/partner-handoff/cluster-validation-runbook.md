# Cluster Validation Runbook (Partner Handoff Reliability Gate)

## Purpose
Execute a repeatable reliability gate against the live cluster backend so dashboard integration remains stable against:
- `plans/partner-handoff/01-product-flow.md`
- `plans/partner-handoff/02-api-contract.md`
- `plans/partner-handoff/03-live-stream-contract.md`
- `plans/partner-handoff/04-frontend-integration-checklist.md`

## Prerequisites
1. Local tunnel is active to DGX backend (`ops/scripts/cluster_tunnel.expect`).
2. `http://127.0.0.1:8000/health` returns `{"status":"ok"}`.
3. Local dependencies are installed (`uv sync --extra dev`).
4. `ops/scripts/cluster_exec.expect` works from this machine (secrets configured).
5. Backend on cluster includes the big fixes (BUG-001 and BUG-002) on target branch/SHA.

## Gate Command
Run from repo root:

```bash
bash ops/scripts/cluster_sandbox_contract_gate.sh
```

Optional overrides:

```bash
CLUSTER_VALIDATION_PASSES=3 \
BASE_HTTP_URL=http://127.0.0.1:8000 \
BASE_WS_URL=ws://127.0.0.1:8000 \
DGX_RUNNER_DIR='$HOME/pantherHacks_runner' \
bash ops/scripts/cluster_sandbox_contract_gate.sh
```

## What the Gate Executes
1. Preflight health check (`/health`).
2. BUG-001 gate: `uv run pytest -q` (must be fully green).
3. For each pass (default `3` consecutive passes):
4. BUG-002 probe over `cluster_exec.expect`:
5. Creates root-owned probe files in runner dir, runs detached DGX script with `DGX_FORCE_CLEAN_RUNNER=1`, checks no `Permission denied`, validates sampled `artifacts/` and `runs/` files are owned by invoking DGX user.
6. Live contract harness:
7. `RUN_CLUSTER_TESTS=1 uv run pytest tests/cluster/test_sandbox_contract_live.py -q`

## Evidence Output
All artifacts are written to:

```text
artifacts/cluster_validation/<timestamp>/
```

Key files:
- `metadata.json` (local+remote branch/SHA, URLs, runner dir)
- `pytest_full.log` (BUG-001 pre-check)
- `pass_<n>/bug002_probe.log`
- `pass_<n>/cluster_contract.log`
- `pass_<n>/assertion_summary.json`
- `final_status.json`

## Failure Triage Map
- Product flow failures (`queued/running/terminal/cancel/reconnect`) -> inspect `pass_<n>/assertion_summary.json` under `doc01_product_flow`, then compare with `01-product-flow.md`.
- API contract failures (`catalog/create/status/cancel/errors`) -> inspect `doc02_api_contract`, then compare with `02-api-contract.md`.
- Stream envelope/order/reconnect failures -> inspect `websocket_transcript.json` and `doc03_live_stream_contract`, then compare with `03-live-stream-contract.md`.
- Frontend integration fallback/terminal summary readiness failures -> inspect `doc04_frontend_integration_checklist`, then compare with `04-frontend-integration-checklist.md`.
- BUG-001 regression -> inspect `pytest_full.log` for non-green suite.
- BUG-002 regression -> inspect `bug002_probe.log` and remote `.cluster_bug002_probe_run.log` in runner dir.

## Updating the Partner Report
After a full successful gate, generate a new handoff report:

`plans/partner-handoff/cluster-backend-test-report-<date>.md`

Populate PASS/FAIL rows directly from `assertion_summary.json` and attach BUG-001/BUG-002 results from gate logs.
