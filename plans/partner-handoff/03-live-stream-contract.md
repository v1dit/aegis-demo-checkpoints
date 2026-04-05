# Partner Handoff 03: Live Stream Contract

## Endpoint
- `WS /stream/live/{run_id}`

## Message Envelope (Frozen)
```json
{
  "type": "action",
  "event_type": "action",
  "payload": { "step": 4, "actor": "BLUE", "action_type": "isolate_host", "target_host": "host-01" },
  "run_id": "run_20260404_190122_001"
}
```

## Event Types
- `action`: defense or attack action event
- `metric`: per-step metrics update
- `marker`: terminal status event (`completed`, `failed`, `cancelled`)

## Ordering and Reconnect Rules
- Ordering is step-ordered within an active connection.
- On disconnect, frontend should reconnect to the same websocket path.
- Frontend must poll `GET /sandbox/runs/{run_id}` every 2-5 seconds as backup truth source.
- If run is terminal and no marker was seen due to disconnect, UI must treat status endpoint as authoritative terminal state.

## Terminal Behavior
- Run is complete only after terminal `marker` or terminal status from polling.
- UI must stop live animation on terminal state and render final summary panel.
