# 03 - Live Stream Contract

This document freezes the partner-facing websocket contract for run live updates.

## Endpoint

- WebSocket path: `/stream/live/{run_id}`

## Message Envelope (Frozen)

Every websocket message must match this envelope:

```json
{
  "type": "action",
  "payload": {}
}
```

Where `type` is one of:

- `"action"`
- `"metric"`
- `"marker"`

Canonical shape to freeze:

```json
{ "type": "action" | "metric" | "marker", "payload": { } }
```

## Payload Families

### `type = "action"`

Represents timeline-worthy execution events.

Example:

```json
{
  "type": "action",
  "payload": {
    "step": 12,
    "timestamp": "2026-04-04T20:11:31Z",
    "actor": "red-team",
    "action": "exploit_attempt",
    "node_id": "workstation-1",
    "result": "blocked"
  }
}
```

### `type = "metric"`

Represents KPI or telemetry updates.

Example:

```json
{
  "type": "metric",
  "payload": {
    "step": 12,
    "timestamp": "2026-04-04T20:11:31Z",
    "kpis": {
      "detections": 2,
      "objective_completion": 0.33
    }
  }
}
```

### `type = "marker"`

Represents lifecycle boundaries and terminal signals.

Example terminal marker:

```json
{
  "type": "marker",
  "payload": {
    "step": 120,
    "timestamp": "2026-04-04T20:13:04Z",
    "status": "completed"
  }
}
```

## Delivery Semantics

- Ordered-by-step guarantee exists only within a single active connection.
- Reconnects can introduce gaps for missed events while disconnected.
- Frontend must not assume lossless replay from websocket alone.
- Terminal `marker` is guaranteed to be emitted by the producer; client receipt is not guaranteed if disconnected.

## Reconnect and Reconciliation Rules

On disconnect or websocket error:

1. Frontend reopens `/stream/live/{run_id}` with backoff.
2. Frontend reconciles current truth via `GET /sandbox/runs/{run_id}` polling.
3. Frontend updates terminal/non-terminal state from status API as source of truth.
4. Frontend resumes live rendering from newly received websocket messages.

## Terminal Behavior

- `completed`: stop reconnect attempts after status confirms terminal; show success summary.
- `failed`: stop reconnect attempts after status confirms terminal; show error summary from `error` when available.
- `cancelled`: stop reconnect attempts after status confirms terminal; show cancelled summary.

For all terminal states, `RunTerminalSummary` is rendered from status API data, not websocket-only state.
