# Partner Handoff 02: API Contract

## EpisodeSpec (Frozen)
```json
{
  "name": "string",
  "seed": 1337,
  "horizon": 150,
  "nodes": [{ "id": "host-01", "severity": "high", "role": "db" }],
  "vulnerabilities": [{ "node_id": "host-01", "vuln_id": "SYNTH-CVE-2026-1301", "exploitability": 0.9 }],
  "red_objectives": [{ "target_node_id": "host-01", "objective": "exfiltrate", "priority": 10 }],
  "defender_mode": "aegis"
}
```

## Endpoints

### `GET /sandbox/catalog`
Returns allowed vulnerability IDs and objective IDs.

Response:
```json
{
  "vulnerabilities": ["SYNTH-CVE-2026-1001"],
  "objectives": ["exfiltrate", "lateral_move", "privilege_escalate", "persist"]
}
```

### `POST /sandbox/runs`
Creates a run.

Request:
```json
{ "episode_spec": { "name": "demo", "horizon": 120, "nodes": [{ "id": "host-01", "severity": "high" }], "vulnerabilities": [], "red_objectives": [], "defender_mode": "aegis" } }
```

Response:
```json
{
  "run_id": "run_20260404_190122_001",
  "status": "queued",
  "stream_url": "/stream/live/run_20260404_190122_001"
}
```

### `GET /sandbox/runs/{run_id}`
Returns run state and summary.

Response:
```json
{
  "run_id": "run_20260404_190122_001",
  "status": "running",
  "created_at": "2026-04-04T19:01:22Z",
  "started_at": "2026-04-04T19:01:23Z",
  "ended_at": null,
  "kpis": null,
  "error": null,
  "artifact_paths": {}
}
```

### `POST /sandbox/runs/{run_id}/cancel`
Requests cancellation.

Response:
```json
{
  "run_id": "run_20260404_190122_001",
  "status": "cancelled"
}
```

## Validation Constraints (v1)
- `1 <= nodes <= 30`
- `10 <= horizon <= 300`
- max 3 vulnerabilities per node
- max 20 red objectives
- all vuln/objective references must point to existing nodes

## Error Codes
- `400`: invalid payload/validation failure
- `404`: unknown `run_id`
- `409`: state conflict
- `429`: rate limit or concurrency cap reached
- `500`: unexpected server failure
