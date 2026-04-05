# Cluster Backend Test Report (Dashboard Integration Reliability)

## Test Metadata
- Report date (UTC): `2026-04-05`
- Validation window (UTC): `2026-04-05T01:58:18Z` to `2026-04-05T02:05:25Z`
- Result: `PASS`
- Required consecutive passes: `3`
- Completed consecutive passes: `3`
- Local branch: `codex/fix-cluster-backend-bugs`
- Local commit SHA: `e64aa04d66a219c197358ee9911109f99ed1ba04`
- Remote branch: `main`
- Remote commit SHA: `e64aa04d66a219c197358ee9911109f99ed1ba04`
- Base HTTP URL: `http://127.0.0.1:8000`
- Base WS URL: `ws://127.0.0.1:8000`
- Runner dir (raw): `$HOME/pantherHacks_runner_api_test`
- Evidence root: `artifacts/cluster_validation/20260405_015807`

## Gate Execution
1. `uv run pytest -q` (BUG-001 gate precheck)
2. BUG-002 ownership/cleanup probe
3. `RUN_CLUSTER_TESTS=1 uv run pytest tests/cluster/test_sandbox_contract_live.py -q`
4. Repeat steps 2-3 until 3 consecutive full passes complete

## Partner Handoff Contract Coverage (Docs 01-04)

| Partner Doc | Required behavior group | Pass 1 | Pass 2 | Pass 3 | Final |
|---|---|---|---|---|---|
| 01 Product Flow | Synthetic client flow (`catalog -> create -> ws -> poll -> cancel -> terminal`) and reconnect/poll resilience | PASS | PASS | PASS | PASS |
| 02 API Contract | Catalog/create/status/cancel contract + negative cases (`400/404/429`) | PASS | PASS | PASS | PASS |
| 03 Live Stream Contract | Envelope keys, `action/metric/marker`, exactly one terminal marker, reconciliation consistency | PASS | PASS | PASS | PASS |
| 04 Frontend Checklist | WS-drop fallback to polling + terminal-summary readiness (`completed/failed/cancelled`) | PASS | PASS | PASS | PASS |

### Notes on State Visibility
- `queued` was consistently observed at create response time.
- `running` was observed in cancel-path polling histories (`running -> cancelled`) across all 3 passes.
- Happy-path polling snapshots reached terminal quickly (`completed`) after stream progression.

## Bug-Fix Status (BUG-001 / BUG-002)

| Bug ID | Area | Verification performed | Evidence | Status |
|---|---|---|---|---|
| BUG-001 | CLI eval regression | Full backend suite gate precheck `uv run pytest -q` completed green (with one expected skipped test and warnings only) | `artifacts/cluster_validation/20260405_015807/pytest_full.log` | RESOLVED / VERIFIED |
| BUG-002 | DGX ownership and cleanup hygiene | Per-pass forced cleanup path invoked with `DGX_FORCE_CLEAN_RUNNER=1`; ownership probe validated sampled `artifacts/` and `runs/` files match invoking DGX user and no permission-denied cleanup failures | `pass_1..pass_3/bug002_force_clean.log`, `pass_1..pass_3/bug002_probe.log` | RESOLVED / VERIFIED |

## Per-Pass Evidence Index
- Pass 1:
  - `artifacts/cluster_validation/20260405_015807/pass_1/assertion_summary.json`
  - `artifacts/cluster_validation/20260405_015807/pass_1/websocket_transcript.json`
  - `artifacts/cluster_validation/20260405_015807/pass_1/cluster_contract.log`
  - `artifacts/cluster_validation/20260405_015807/pass_1/bug002_probe.log`
- Pass 2:
  - `artifacts/cluster_validation/20260405_015807/pass_2/assertion_summary.json`
  - `artifacts/cluster_validation/20260405_015807/pass_2/websocket_transcript.json`
  - `artifacts/cluster_validation/20260405_015807/pass_2/cluster_contract.log`
  - `artifacts/cluster_validation/20260405_015807/pass_2/bug002_probe.log`
- Pass 3:
  - `artifacts/cluster_validation/20260405_015807/pass_3/assertion_summary.json`
  - `artifacts/cluster_validation/20260405_015807/pass_3/websocket_transcript.json`
  - `artifacts/cluster_validation/20260405_015807/pass_3/cluster_contract.log`
  - `artifacts/cluster_validation/20260405_015807/pass_3/bug002_probe.log`

## Stability Verdict
- Dashboard integration contract validation is stable at synthetic-client depth for the backend under test.
- Acceptance criteria satisfied: doc-mapped contract checks pass in 3 consecutive live-cluster runs, BUG-001 gate green, BUG-002 cleanup/ownership probe green, and websocket/poll reconciliation consistent.

## Operational Observations
- `/health` returned `404` during these runs; gate fallback to `/sandbox/catalog` preflight was used successfully.
- This did not impact sandbox contract validation outcomes.
