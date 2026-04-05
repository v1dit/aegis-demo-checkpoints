# 02 - API Contract

This document freezes partner-facing REST contracts for sandbox execution.

## Base Contract Rules

- Content type: `application/json`
- Versioning: current unversioned paths under `/sandbox/*`
- Timestamps: ISO 8601 UTC strings
- Status enum: `queued | running | completed | failed | cancelled`

## Canonical `EpisodeSpec`

`EpisodeSpec` must use exactly these fields:

- `name` (string, required)
- `seed` (integer, optional)
- `horizon` (integer, required)
- `nodes` (array, required)
- `vulnerabilities` (array, required)
- `red_objectives` (array, required)
- `defender_mode` (string, required, must equal `"aegis"`)

### Field Constraints

- `name`: 1-120 chars.
- `seed`: 0 to 2,147,483,647.
- `horizon`: integer 1-10,000.
- `nodes`: at least 1 entry.
- `vulnerabilities`: zero or more entries.
- `red_objectives`: at least 1 entry.
- `defender_mode`: only `"aegis"` accepted.

## Endpoints

### `POST /sandbox/runs`

Creates a new run from `EpisodeSpec`.

Request body:

```json
{
  "name": "Ransomware lateral movement drill",
  "seed": 4242,
  "horizon": 120,
  "nodes": [
    { "id": "workstation-1", "role": "endpoint", "os": "windows" },
    { "id": "db-1", "role": "database", "os": "linux" }
  ],
  "vulnerabilities": [
    { "id": "cve-2025-10001", "node_id": "workstation-1", "severity": "high" }
  ],
  "red_objectives": [
    { "id": "obj-exfiltrate-db", "type": "data_exfiltration", "target": "db-1" }
  ],
  "defender_mode": "aegis"
}
```

Success response `201` (frozen):

```json
{
  "run_id": "run_01JX9S8W0A7YF5T6Q2V4Z8M1N3",
  "status": "queued",
  "stream_url": "/stream/live/run_01JX9S8W0A7YF5T6Q2V4Z8M1N3"
}
```

### `GET /sandbox/runs/{run_id}`

Returns latest run status.

Success response `200` (frozen fields):

```json
{
  "run_id": "run_01JX9S8W0A7YF5T6Q2V4Z8M1N3",
  "status": "running",
  "started_at": "2026-04-04T20:11:24Z",
  "ended_at": null,
  "kpis": {
    "detections": 4,
    "containment_time_sec": 58,
    "objective_completion": 0.5
  },
  "error": null
}
```

Notes:

- `started_at` and `ended_at` are optional and may be omitted or `null` when unavailable.
- `kpis` is optional and may be omitted or `null` before metrics are available.
- `error` is optional and may be omitted or `null` unless `status = "failed"`.

### `POST /sandbox/runs/{run_id}/cancel`

Requests cancellation for an active or queued run.

Request body: empty JSON object `{}` (or omitted body).

Success response `202`:

```json
{
  "run_id": "run_01JX9S8W0A7YF5T6Q2V4Z8M1N3",
  "status": "cancelled"
}
```

### `GET /sandbox/catalog`

Returns catalog metadata used by the builder.

Success response `200`:

```json
{
  "node_templates": [
    { "role": "endpoint", "supported_os": ["windows", "linux", "macos"] },
    { "role": "database", "supported_os": ["linux"] }
  ],
  "vulnerability_templates": [
    { "id": "cve-2025-10001", "severity": "high" }
  ],
  "objective_templates": [
    { "type": "data_exfiltration" },
    { "type": "lateral_movement" }
  ]
}
```

## Error Response Format (Frozen)

All error responses use:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "red_objectives must contain at least one item",
    "details": [
      {
        "field": "red_objectives",
        "issue": "min_items",
        "expected": 1,
        "actual": 0
      }
    ]
  }
}
```

### Error Codes by HTTP Status

- `400 Bad Request`: invalid payload, missing required fields, enum/type violations.
- `404 Not Found`: `run_id` does not exist.
- `409 Conflict`: run state conflict (for example, cancel after terminal state).
- `429 Too Many Requests`: client exceeds request limits.
- `500 Internal Server Error`: unexpected backend failure.
