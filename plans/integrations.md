# Track B Dashboard Integrations Guide

This doc is the contract for Track B to build dashboard views on top of Track A outputs.

## 1) API Endpoints (authoritative)

- `POST /train/run`
  - Starts a training run.
  - Request body supports:
    - `seed` (int, optional)
    - `profile` (string, optional)
    - `fresh_start` (bool, optional; default false)
    - `run_id` (string, optional)
  - Response includes:
    - `run_id`
    - `run.train_id`
    - `run.status`
    - lineage fields when available (`parent_run_id`, `parent_checkpoint`).

- `GET /train/status/{run_id}`
  - Returns lifecycle state for the training job.
  - Use this for status pills and progress polling.

- `POST /eval/run`
  - Starts evaluation for a checkpoint (or current run default).
  - Response includes `eval_id` and `run_id`.

- `GET /eval/report/{eval_id}`
  - Returns full eval report payload plus `run_id`.

- `GET /replay/list`
  - Lists replay bundles for the current active run.
  - Use for active-run replay picker.

- `GET /replay/{id}/bundle`
  - Returns bundle metadata/paths for selected replay in the active run.

- `GET /replay/runs`
  - Lists available run history with lifecycle summary:
    - `run_id`
    - `created_at`, `updated_at`
    - `train_status`, `eval_status`, `replay_status`
    - `replay_count`

- `GET /replay/runs/{run_id}/list`
  - Lists replay bundles for a specific historical run.
  - Use for run-scoped replay picker.

- `GET /replay/runs/{run_id}/{replay_id}/bundle`
  - Returns replay bundle metadata/paths for a specific run + replay.

## 2) WebSocket Streams

- `WS /stream/live/{session_id}`
  - Live event stream for in-progress scenario playback.
  - Event ordering is deterministic by step clock.

- `WS /stream/replay/{replay_id}`
  - Replay stream for active run replay, with legacy artifacts fallback.
  - Use this for default scrubber/time-travel UI.

- `WS /stream/replay/{run_id}/{replay_id}`
  - Replay stream for a specific historical run.
  - Use this when viewing run history pages.

## 3) Canonical Run Bundle Layout

All stage outputs for one execution are rooted at:

`runs/<run_id>/`

Expected structure:

- `runs/<run_id>/train/`
  - checkpoint json(s)
  - train metrics/logs
- `runs/<run_id>/eval/`
  - `eval_report_latest.json`
  - eval-by-id reports
- `runs/<run_id>/replays/`
  - hero and alternate replay folders
  - each replay has `events.jsonl`, `metrics.json`, `topology_snapshots.json`, `manifest.json`
- `runs/<run_id>/manifest.json`
  - single source of truth for paths + lineage + KPI deltas

## 4) Manifest Fields Track B Should Read First

From `runs/<run_id>/manifest.json`:

- `run_id`
- `created_at`
- `status`
- `parent_run_id`
- `parent_checkpoint`
- `best_checkpoint`
- `kpis`
- `improvement_delta`
- `artifacts.train`
- `artifacts.eval`
- `artifacts.replays`

Use this file to drive:

- run history table
- model-improvement panel (delta vs parent)
- “open replay” actions
- deep links into eval report and best checkpoint

## 5) Dashboard Narrative Mapping

Recommended panels:

- Run Lineage
  - Show `run_id -> parent_run_id` chain.
- Improvement
  - Render KPI deltas from `improvement_delta`.
  - Display green/red/flat per metric.
- Gate Status
  - Read eval gate outcomes from eval report.
- Replay Explorer
  - Show hero + alternates and allow WS replay stream.
- Explainability
  - Surface action-level explainability records from replay/event payloads.

## 6) Backward Compatibility (important)

Track A still updates legacy latest artifacts under:

- `artifacts/checkpoints/`
- `artifacts/eval_reports/`
- `artifacts/replays/`

Track B should prefer `runs/<run_id>/...` for correctness and history, but may use `artifacts/*` as fallback.

## 7) Suggested Polling + Refresh Behavior

- Train page: poll `GET /train/status/{run_id}` every 2-5s.
- Eval page: after `POST /eval/run`, poll until terminal state then fetch full report.
- Replay page (active): call `GET /replay/list` on load, refresh on run completion.
- Replay page (history): call `GET /replay/runs`, then `GET /replay/runs/{run_id}/list`.

## 8) Demo-Ready Claims You Can Safely Make

- “Each new run can continue from the previous best checkpoint.”
- “Dashboard shows measurable KPI deltas between parent and child runs.”
- “Every run is fully auditable from one manifest and one run folder.”
- “Replays are deterministic for fixed `(seed, scenario, checkpoint)` when `fresh_start=true`.”

## 9) Minimal UI Data Contract Checklist

Before integrating, verify these are available in API payloads or run manifest:

- `run_id`
- lineage (`parent_run_id`, `parent_checkpoint`)
- KPI summary + deltas
- replay IDs and bundle pointers
- eval gate statuses
- run history summary (`train_status`, `eval_status`, `replay_status`, `replay_count`)

If any key is missing, fall back to `runs/<run_id>/manifest.json` as canonical source.
