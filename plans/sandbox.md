# Sandbox: Build-Your-Own Episode (Live Aegis)

## Goal
Enable users to create a custom cyber episode in the dashboard and run Aegis live against it.

The user experience should be:
1. Build environment (nodes + severity)
2. Plant vulnerabilities / choose bugs
3. Define red-team objectives/targets
4. Click **Run Live**
5. Watch Aegis execute in real time (cluster-backed)

## Product Scope (v1)
- Guided form builder only (no free-form DSL editor)
- Anonymous users allowed (no auth required)
- Strict server-side validation and rate limiting
- Async run jobs with `run_id`
- Live telemetry stream for in-progress runs

## Architecture

### Runtime split
- **Frontend (Vercel):** UI only (builder, run controls, live dashboard)
- **Backend API (public control plane):** validates specs, queues jobs, serves run status + stream relay
- **Cluster workers:** execute Aegis/model episode runs, emit live events, persist artifacts

### Why async jobs
Use `run_id` based async execution instead of long-lived in-request sessions:
- Better reliability under load
- Easy resume/reconnect from frontend
- Clear lifecycle (`queued`, `running`, `completed`, `failed`, `cancelled`)

## Data Model

### EpisodeSpec
```ts
export type Severity = "low" | "medium" | "high";

export type EpisodeNode = {
  id: string;            // stable identifier in this episode
  severity: Severity;    // user-selected impact tier
  role?: string;         // optional (db, api, gateway, etc)
};

export type EpisodeVulnerability = {
  node_id: string;       // must reference EpisodeNode.id
  vuln_id: string;       // from server-approved vulnerability catalog
  exploitability?: number; // optional normalized score [0..1]
};

export type RedObjective = {
  target_node_id: string; // must reference EpisodeNode.id
  objective: string;      // e.g. exfiltrate, lateral_move, persist
  priority?: number;      // optional ordering weight
};

export type EpisodeSpec = {
  name: string;
  seed?: number;
  horizon: number;
  nodes: EpisodeNode[];
  vulnerabilities: EpisodeVulnerability[];
  red_objectives: RedObjective[];
  defender_mode: "aegis";
};
```

## API Contracts

### 1) Create sandbox run
`POST /sandbox/runs`

Request:
```json
{
  "episode_spec": {
    "name": "Ransomware Drill A",
    "horizon": 150,
    "nodes": [{ "id": "host-01", "severity": "high" }],
    "vulnerabilities": [{ "node_id": "host-01", "vuln_id": "CVE_SIM_001" }],
    "red_objectives": [{ "target_node_id": "host-01", "objective": "exfiltrate" }],
    "defender_mode": "aegis"
  }
}
```

Response:
```json
{
  "run_id": "run_20260404_190122_001",
  "status": "queued",
  "stream_url": "wss://api.example.com/stream/live/run_20260404_190122_001"
}
```

### 2) Get run status
`GET /sandbox/runs/{run_id}`

Response:
```json
{
  "run_id": "run_20260404_190122_001",
  "status": "running",
  "started_at": "2026-04-04T19:01:30Z",
  "ended_at": null,
  "kpis": null,
  "error": null
}
```

### 3) Cancel run
`POST /sandbox/runs/{run_id}/cancel`

Response:
```json
{
  "run_id": "run_20260404_190122_001",
  "status": "cancelled"
}
```

### 4) Live stream
`WS /stream/live/{run_id}`

Event envelope:
```json
{ "type": "action", "payload": { "step": 12, "actor": "BLUE", "action": "isolate", "target": "host-01" } }
{ "type": "metric", "payload": { "damage": 23.4, "compromised_hosts": 2, "step": 12 } }
{ "type": "marker", "payload": { "status": "completed" } }
```

## Frontend Integration (Dashboard)

### Builder UX
1. **Nodes step**
- Add/remove nodes
- Set severity (`low/medium/high`)
- Optional role tag

2. **Vulnerabilities step**
- Select node
- Add one or more vulns from catalog
- Optional exploitability slider

3. **Red-team objectives step**
- Select targets and objective types
- Optional priority tuning

4. **Review + Run step**
- Show generated EpisodeSpec JSON preview (read-only)
- Submit to `POST /sandbox/runs`

### Live run UX
- On submit, store `run_id`
- Open websocket using returned `stream_url`
- Render event timeline + graph updates + metrics cards
- Poll `GET /sandbox/runs/{run_id}` every 2-5s as backup status channel
- On terminal marker or status terminal state, freeze stream and show summary KPIs

## Backend/Cluster Execution Flow
1. API receives `EpisodeSpec`
2. Validate and normalize spec
3. Enqueue job with generated `run_id`
4. Worker picks job and starts simulation/inference on cluster
5. Worker publishes step events and metrics via pub/sub channel keyed by `run_id`
6. Stream service relays events to websocket clients
7. Worker persists final artifacts and run summary
8. API status endpoint serves current and terminal state

## Validation Rules (must enforce server-side)
- `nodes.length` within configured limit (example: 1..50)
- unique node IDs per episode
- `horizon` bounded (example: 10..500)
- vulnerability IDs must exist in approved catalog
- vulnerability `node_id` and objective `target_node_id` must reference existing nodes
- objective types must be from approved enum
- reject malformed or oversized payloads early

## Reliability + Safety (v1 minimum)
- Per-IP/session rate limit on run creation
- Max concurrent runs per IP/session
- Job timeout (hard stop) and heartbeat watchdog
- Explicit failure reasons surfaced in run status
- CORS restricted to known frontend origins (replace wildcard in production)

## Storage / Artifacts
Persist by `run_id`:
- `episode_spec.json`
- `events.jsonl` (or equivalent stream log)
- `summary.json` (terminal KPIs + metadata)
- optional replay bundle for post-run playback

## Suggested Mapping to Current Codebase
- Extend FastAPI routers with sandbox endpoints (parallel to existing train/eval routes)
- Reuse existing stream infrastructure for `run_id` keyed live streams
- Reuse run directory conventions under `runs/<run_id>/...`
- Keep existing replay viewer as fallback when no live run active

## Acceptance Criteria
- User can build a custom episode entirely in dashboard and submit without manual JSON editing
- Submitted run executes on cluster and streams live events into UI
- UI handles reconnects and still reaches correct terminal state
- Terminal status, KPIs, and artifacts are queryable by `run_id`
- Invalid specs are rejected with clear errors

## Non-Goals (v1)
- Multi-user collaboration on one episode
- Free-form scripting/DSL for attacker behavior
- Public sharing marketplace for custom episodes

## Future Enhancements
- Auth + saved episode library
- Shareable episode templates
- Advanced mode with JSON editor
- Cost controls and per-org quota policies
