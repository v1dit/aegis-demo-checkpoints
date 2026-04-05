# Cluster Backend Test Report (Sandbox Dashboard)

## Test Metadata
- Tested commit SHA: `4c964efe5fd09ec53ecc2beffad3adfaf3d9d22e`
- Branch: `main`
- DGX host: `fowler-lpw-dgx-0`
- Remote runner dir: `$HOME/pantherHacks_runner_api_test`
- Docker image: `pantherhacks-trainer:latest`
- API container: `ee8f327762be`
- Remote API health: `{"status":"ok"}`
- Local tunnel health (`localhost:8000`): `{"status":"ok"}`
- Tunnel mode: `ops/scripts/cluster_tunnel.expect` (`-L 8000:localhost:8000`)

## Pass/Fail Checklist by Partner Docs

### Doc 01 - Product Flow
- PASS: Backend supports create, queue/run, terminal complete, and cancel path.
- PASS: Error path returns validation failures (`400`) for invalid payloads.

### Doc 02 - API Contract
- PASS: `GET /sandbox/catalog` returns `vulnerabilities[]` and `objectives[]`.
- PASS: `POST /sandbox/runs` returns `run_id`, `status=queued`, `stream_url`.
- PASS: `GET /sandbox/runs/{run_id}` transitions through runtime lifecycle.
- PASS: `POST /sandbox/runs/{run_id}/cancel` reaches `cancelled`.
- PASS: Negative cases:
  - invalid horizon (`<10`) -> `400`
  - unknown vuln_id -> `400`
  - unknown run_id -> `404`
  - rate limit/concurrency cap -> `429`

### Doc 03 - Live Stream Contract
- PASS: `ws://127.0.0.1:8000/stream/live/{run_id}` streams action + metric + terminal marker.
- PASS: Message envelopes include `type`/`event_type`, `payload`, `run_id`.
- PASS: Reconnect mid-run + polling reconciliation reaches consistent terminal truth.
- PASS: Exactly one terminal marker observed in run stream test.

### Doc 04 - Frontend Integration Checklist
- PASS: Backend behavior supports expected dashboard states (`submitting`, `queued`, `running`, terminal states).
- PASS: Disconnect fallback is viable (polling remains authoritative).
- PASS: Legacy stream compatibility still works for `/stream/live/{session_id}`.

## Contract Scenario Results
- PASS: Happy path run completion with KPIs populated.
- PASS: Cancel path reaches `cancelled`.
- PASS: Validation rejection scenarios.
- PASS: Concurrency and rate guardrails.
- PASS: Reconnect resilience.
- PASS: Legacy live session stream compatibility.

## Regression Check Results
- PASS: `uv run pytest tests/integration/test_sandbox_api.py tests/integration/test_sandbox_streaming.py tests/integration/test_streaming.py -q`
- PASS: `uv run ruff check backend/app/api/sandbox.py backend/app/sandbox backend/app/api/stream.py backend/app/env/simulator.py backend/app/schemas/contracts.py`
- FAIL: `uv run pytest -q` (1 failing test outside sandbox scope)

## Bug Table

| ID | Severity | Area | Steps to Reproduce | Expected | Actual | Evidence | Status | Owner |
|---|---|---|---|---|---|---|---|---|
| BUG-001 | P2 | CLI Regression (non-sandbox) | Run `uv run pytest -q` | Full suite passes | `test_cli_eval_prefers_latest_checkpoint_file_when_no_in_memory_checkpoint` fails with `TypeError: _run_eval() missing 2 required positional arguments: 'suite_id' and 'eval_seeds'` | `tests/unit/test_dgx_orchestration_regressions.py:100` failure in pytest output | Open | Backend |
| BUG-002 | P3 | DGX Runner Hygiene | Run repo sync in existing `$HOME/pantherHacks_runner` with `rm -rf` cleanup | Runner directory can be reset for fresh test launch | Cleanup fails with multiple `Permission denied` errors under `artifacts/replays/*` and `runs/*` due root-owned files from container writes | DGX sync command output before switching to `$HOME/pantherHacks_runner_api_test` | Open | Infra |

## Known Pre-existing vs New Regressions
- Pre-existing/non-sandbox regression observed: **BUG-001** (CLI eval unit test signature mismatch).
- New infra issue observed during cluster test setup: **BUG-002** (permission hygiene in long-lived runner dir).
- No new sandbox contract or websocket regressions were found in cluster-backed validation.
