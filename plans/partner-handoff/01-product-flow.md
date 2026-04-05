# 01 - Product Flow

This document freezes the partner-facing product flow for the sandbox run experience.

## End-to-End User Flow

1. Build Nodes.
2. Add Vulnerabilities.
3. Set Red Objectives.
4. Run Live.
5. View Timeline/KPIs.

## UI State Machine

The UI state machine for run execution is fixed to the following states:

- `idle`: No active submit in progress; form is editable.
- `validating`: Client-side and request-shape validation is running.
- `submitting`: `POST /sandbox/runs` in flight.
- `queued`: Run accepted and queued; awaiting execution start.
- `running`: Run active; live stream and metrics updates expected.
- `completed`: Run reached successful terminal state.
- `failed`: Run reached unsuccessful terminal state.
- `cancelled`: Run cancelled by user or system action.

Allowed transition map:

- `idle -> validating`
- `validating -> submitting`
- `validating -> idle` (validation error)
- `submitting -> queued`
- `submitting -> failed` (request/server failure)
- `queued -> running`
- `queued -> cancelled`
- `running -> completed`
- `running -> failed`
- `running -> cancelled`

No other transitions are allowed in the frontend model.

## Required Screens and Components

- `SandboxBuilder`: Builder form for nodes, vulnerabilities, and red objectives.
- `RunControls`: Start/cancel controls and run status badge.
- `RunTimeline`: Ordered event timeline for actions/markers.
- `LiveMetricsPanel`: KPI and metric cards with live refresh.
- `RunTerminalSummary`: Final outcome summary for terminal state.

## Empty, Loading, and Error States

### `SandboxBuilder`

- Empty:
  - Condition: no nodes configured.
  - Message: `No nodes configured yet. Add at least one node to continue.`
- Loading:
  - Condition: catalog request in progress.
  - Message: `Loading sandbox catalog...`
- Error:
  - Condition: catalog request failed.
  - Message: `Could not load sandbox catalog. Retry to continue.`

### `RunControls`

- Empty:
  - Condition: no run created yet.
  - Message: `Configure the sandbox and click Run Live.`
- Loading:
  - Condition: create/cancel request in progress.
  - Message: `Submitting run request...`
- Error:
  - Condition: create/cancel request failed.
  - Message: `Run request failed. Check inputs and try again.`

### `RunTimeline`

- Empty:
  - Condition: run exists but no stream events yet.
  - Message: `Waiting for first live events...`
- Loading:
  - Condition: stream connecting/reconnecting.
  - Message: `Connecting to live stream...`
- Error:
  - Condition: stream disconnected with no immediate recovery.
  - Message: `Live stream disconnected. Reconnecting and syncing status...`

### `LiveMetricsPanel`

- Empty:
  - Condition: no metric payloads received yet.
  - Message: `Metrics will appear when the run starts producing data.`
- Loading:
  - Condition: run is `queued` or stream is connecting.
  - Message: `Waiting for live metrics...`
- Error:
  - Condition: metric payload parse/render failure.
  - Message: `Some metrics could not be displayed. Data sync will continue.`

### `RunTerminalSummary`

- Empty:
  - Condition: state not terminal.
  - Message: `Run is in progress. Terminal summary appears when finished.`
- Loading:
  - Condition: terminal marker seen; final status reconciliation pending.
  - Message: `Finalizing run summary...`
- Error:
  - Condition: terminal details unavailable.
  - Message: `Run ended but summary details are unavailable. Check run status.`
