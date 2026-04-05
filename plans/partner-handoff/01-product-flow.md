# Partner Handoff 01: Product Flow

## Goal
Enable users to build a custom episode and run Aegis live from the website against cluster-backed execution.

## User Flow
1. Build Nodes
2. Add Vulnerabilities
3. Set Red Objectives
4. Run Live
5. Watch Timeline and KPIs

## UI State Machine
- `idle`: Builder open, no pending request.
- `validating`: Client-side checks running.
- `submitting`: `POST /sandbox/runs` in flight.
- `queued`: Run accepted, waiting for execution.
- `running`: Live stream active and receiving events.
- `completed`: Terminal success with KPI summary.
- `failed`: Terminal error with reason and retry option.
- `cancelled`: Terminal stop requested by user.

## Required Screens and Components
- `SandboxBuilder`
- `RunControls`
- `RunTimeline`
- `LiveMetricsPanel`
- `RunTerminalSummary`

## Empty/Loading/Error Rules
- Empty builder: disable Run button until minimum valid spec.
- Loading (submitting): disable form edits and show spinner.
- Queued/running: show run ID and live connection status.
- Stream disconnect: keep timeline visible, show reconnect banner, continue status polling.
- Failed: show error payload from backend, preserve spec for retry.
