# Partner Handoff 04: Frontend Integration Checklist

## Build Order
1. Build the guided `EpisodeSpec` form and local validation.
2. Integrate `GET /sandbox/catalog` for valid vulnerabilities/objectives and live readiness (`execution_mode`, `live_run_enabled`, `live_block_reason`).
3. Integrate `POST /sandbox/runs` and store returned `run_id`.
4. Open `WS /stream/live/{run_id}` and render timeline updates.
5. Poll `GET /sandbox/runs/{run_id}` for status reconciliation.
6. Add `POST /sandbox/runs/{run_id}/cancel` action and UI state transitions.
7. Render terminal summary using final status and KPI payload.
8. Disable `Run Live` whenever `live_run_enabled=false` and show `live_block_reason`.

## Fallback Rules
- If websocket drops, show reconnect banner and continue polling.
- If polling reports terminal, close websocket and finalize UI.
- If run creation fails with `400`, `409`, or `429`, keep form state and show actionable error.
- Do not auto-switch lanes when sandbox backend call fails.

## Definition of Done
- User can create a valid episode and launch a run.
- Live events appear during `running`.
- Cancel transitions to terminal `cancelled`.
- Terminal summary renders for `completed`, `failed`, and `cancelled`.
- No hard dependency on mock events for sandbox runs.
