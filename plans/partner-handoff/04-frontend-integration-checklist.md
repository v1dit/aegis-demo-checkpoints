# 04 - Frontend Integration Checklist

This checklist defines implementation order and definition of done for partner frontend integration.

## 1. Builder Form and Client-Side Validation

Scope:

- Build `SandboxBuilder` for `EpisodeSpec` fields.
- Enforce required fields and constraints before submit.

Definition of done:

- User can input `name`, optional `seed`, `horizon`, `nodes`, `vulnerabilities`, `red_objectives`, and fixed `defender_mode="aegis"`.
- Validation blocks submit when required fields are missing or invalid.
- Validation messages are user-visible and map to field-level errors.
- `idle -> validating` and `validating -> idle|submitting` transitions are implemented.

## 2. Submit Hook for `POST /sandbox/runs`

Scope:

- Submit valid `EpisodeSpec` payload.
- Store `run_id`, `status`, and `stream_url` from response.

Definition of done:

- Valid submit receives `201` with `run_id`, `status="queued"`, `stream_url`.
- UI transitions `submitting -> queued` on success.
- `400/429/500` failures render clear, user-visible error messages.
- Duplicate submits while `submitting` are prevented.

## 3. Live Stream Hook for WebSocket Events

Scope:

- Connect to `/stream/live/{run_id}`.
- Consume frozen envelope `{ "type": "action" | "metric" | "marker", "payload": {...} }`.

Definition of done:

- `action` events append to `RunTimeline` in step order received.
- `metric` events update `LiveMetricsPanel` without blocking timeline rendering.
- `marker` events drive terminal candidate state in UI.
- Unknown `type` is ignored safely with non-blocking warning logging.

## 4. Status Polling Fallback

Scope:

- Poll `GET /sandbox/runs/{run_id}` during queued/running and reconnect gaps.

Definition of done:

- Polling starts when run enters `queued` and continues through `running`.
- Polling reconciles authoritative `status`, `started_at`, `ended_at`, `kpis`, `error`.
- On websocket disconnect, polling keeps UI status accurate.
- Polling stops when `status` is terminal (`completed|failed|cancelled`).

## 5. Cancel Action Wiring

Scope:

- Wire cancel control to `POST /sandbox/runs/{run_id}/cancel`.

Definition of done:

- Cancel action is enabled for `queued` and `running` only.
- Successful cancel transitions UI to terminal `cancelled` state.
- `404` and `409` responses map to clear user-visible messages.
- Repeated cancel clicks are debounced/disabled while request is in flight.

## 6. Terminal Summary Rendering

Scope:

- Render `RunTerminalSummary` for `completed`, `failed`, and `cancelled`.

Definition of done:

- `completed` summary shows final KPIs from status response.
- `failed` summary shows `error.message` and any available KPI snapshot.
- `cancelled` summary clearly indicates run was stopped before completion.
- Terminal summary rendering is sourced from `GET /sandbox/runs/{run_id}` data after reconciliation.
