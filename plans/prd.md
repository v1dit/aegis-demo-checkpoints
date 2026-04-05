# PRD: Adaptive Cyber Defense via Continuous RL (Hackathon Build)

## 1. Document Control
- Project name: `Adaptive Cyber Defense via Continuous Reinforcement Learning`
- Repo root: `/Users/krishgarg/Documents/Projects/pantherHacks`
- Deployment target: `dgx0.chapman.edu` (Docker-first)
- Timebox: weekend hackathon
- Team:
  - Track A (ML/Backend/Infra): Krish
  - Track B (Dashboard/UI): Partner
- Product mode: expert-grade live demo, reliable under stage conditions

## 2. Product Objective
Build a polished, technically credible, live cyber-battle demo where a Blue RL defender improves against a scripted Red attacker in a procedurally generated network environment.

The result must make two things obvious:
1. The defender actually learns.
2. The system behavior is realistic enough for security experts.

## 3. Non-Negotiable Scope
- Blue agent: trained RL policy.
- Red agent: scripted policy (learning Red deferred).
- Environment: hybrid symbolic cyber range (host-service-vulnerability graph).
- Demo UI: SOC-style 3-layer display.
- Replay packaging: `1 hero + 3 selectable` replays.
- Stage runtime: pre-trained checkpoint + live replay/inference burst.
- Safety: simulation-only offensive semantics, no real exploit payloads, no external targets.

## 4. Non-Goals (v1)
- Full Red-vs-Blue co-training.
- Packet-level simulation.
- Real exploit execution framework.
- Keck/Apptainer parity implementation (documented as portability appendix only).

## 5. Success Criteria

### 5.1 Primary KPI
- Blue damage reduction vs baselines on held-out seeded evaluation suite.

### 5.2 Baselines
- Baseline A: no-defense.
- Baseline B: static rule-based defender.

### 5.3 Quantitative Acceptance Gates
- Blue damage reduction >= 25% vs Baseline A.
- Blue damage reduction >= 15% vs Baseline B.
- Mean detection latency improves >= 20% vs Baseline B.
- Replay sync error budget: <= 100ms drift between graph state, log line, and metric timestamp.

## 6. Demo Experience Requirements

### 6.1 Visual Language
- Dark, minimal, professional dashboard.
- No game/cartoon aesthetics.
- Restricted palette: red (attack), blue (defense), neutral gray/white, warning amber.
- Motion: subtle and state-driven only (node pulse, edge cut, status transition).

### 6.2 Three-Layer Demo Structure
- Layer 1 (AI Learning):
  - Reward curves (Blue vs Red pressure score).
  - Attack success rate over training/eval checkpoints.
  - Blue detection latency trend.
- Layer 2 (Main Visual):
  - Live Cytoscape network graph.
  - Nodes = hosts/services.
  - Edges = connectivity/trust paths.
  - Node/edge state coding:
    - compromised: red fill
    - defended/hardened: blue outline
    - probing/scanning: amber pulse
    - neutral: gray
  - Action effects:
    - scan -> target node amber pulse
    - exploit success -> node red
    - isolate -> edge removed/disabled
    - patch -> vuln badge removed and node blue-hardened
- Layer 3 (Realism + Explainability):
  - Terminal-style time-ordered action log:
    - `[RED]`, `[BLUE]`, `[ENV]`
  - Explainability panel for Blue actions:
    - top reason features
    - confidence score
    - chosen action
    - expected outcome

### 6.3 Mandatory Live Demo Script
1. Weak defender baseline run (problem statement).
2. Trained checkpoint run (improvement visible).
3. Unseen attack scenario injection (generalization proof).
4. Live 20-30 second burst (non-reset dynamic activity).

## 7. Functional Requirements

### 7.1 Environment
- Procedural topology generation:
  - 8-20 hosts.
  - segmented zones (`public`, `app`, `data`, `admin`).
  - services per host sampled from catalog.
  - vulnerabilities sampled from synthetic CVE-like catalog.
- Episode horizon:
  - 200 steps.
- Time model:
  - discrete step engine with event timestamps.
- Dynamics:
  - optional config drift events.
  - optional service restarts/recovery events.

### 7.2 Action Spaces
- Red scripted actions:
  - `scan_host`
  - `enumerate_service`
  - `exploit_vulnerability`
  - `lateral_move`
  - `privilege_escalate`
  - `exfiltrate_data`
- Blue RL actions:
  - `monitor_host`
  - `patch_service`
  - `isolate_host`
  - `block_connection`
  - `rotate_credentials`
  - `deploy_deception`

### 7.3 Reward Model (Blue)
- Positive:
  - early detection
  - successful containment
  - maintained service integrity
  - prevented exfiltration
- Negative:
  - successful compromise
  - delayed response
  - false positive-heavy actions
  - unnecessary isolation cost

### 7.4 MITRE ATT&CK Mapping (Core Subset)
- Required tags per action:
  - `Reconnaissance`
  - `Initial Access`
  - `Execution`
  - `Lateral Movement`
  - `Credential Access`
  - `Exfiltration`
  - `Defense Evasion` (when applicable)

## 8. Technical Architecture

### 8.1 Stack
- Backend: FastAPI (Python 3.10+), Ray RLlib, PettingZoo adapter.
- Frontend: Next.js + Tailwind + Cytoscape.js + chart library.
- Streaming: WebSockets.
- Tracking: MLflow local.
- Artifacts: filesystem (`artifacts/`) + replay bundles.
- Containerization: Docker + Docker Compose.
- Package manager: `uv` for Python environment/tooling.

### 8.2 Logical Services
- `trainer`:
  - runs RL training jobs and checkpointing.
- `api`:
  - train/eval/replay APIs.
  - websocket stream endpoints.
- `replay-builder`:
  - converts runs into portable replay bundles.
- `ui`:
  - dashboard and live replay surface.
- `mlflow`:
  - experiment metadata and artifacts index.

### 8.3 Repository Layout (Required)
```text
pantherHacks/
  backend/
    app/
      api/
      schemas/
      env/
      rl/
      replay/
      explainability/
  frontend/
    src/
      app/
      components/
      lib/
  artifacts/
    checkpoints/
    replays/
    eval_reports/
  infra/
    docker/
    compose/
  ops/
    scripts/
    runbooks/
  tests/
  Makefile
  pyproject.toml
  .env.example
  plans/prd.md
```

## 9. API Contract (Locked)

### 9.1 `POST /train/run`
- Purpose: start a training job.
- Request:
```json
{
  "run_name": "blue_train_main",
  "seed": 42,
  "gpu_ids": [5, 6, 7],
  "max_timesteps": 3000000,
  "config_profile": "weekend_v1"
}
```
- Response:
```json
{
  "run_id": "train_20260404_001",
  "status": "started"
}
```

### 9.2 `GET /train/status/{run_id}`
- Returns current phase, timesteps, checkpoint path, and learning metrics snapshot.

### 9.3 `POST /eval/run`
- Purpose: run fixed seeded eval suite on checkpoint.
- Request:
```json
{
  "checkpoint_id": "ckpt_blue_main_0009",
  "suite_id": "heldout_suite_v1",
  "seeds": [1001, 1002, 1003, 1004]
}
```
- Response:
```json
{
  "eval_id": "eval_20260404_001",
  "status": "started"
}
```

### 9.4 `GET /eval/report/{eval_id}`
- Returns an `EvalReport`.

### 9.5 `GET /replay/list`
- Returns replay metadata list (hero + backups).

### 9.6 `GET /replay/{id}/bundle`
- Returns signed/relative paths or inline metadata to:
  - `events.jsonl`
  - `topology_snapshots.json`
  - `metrics.json`
  - `manifest.json`

### 9.7 `WS /stream/live/{session_id}`
- Streams live events during short burst or live inference mode.

### 9.8 `WS /stream/replay/{replay_id}`
- Streams deterministic replay events for demo.

## 10. Canonical Schemas (Locked)

### 10.1 `ActionEvent`
```json
{
  "event_id": "evt_000001",
  "ts_ms": 1712412345678,
  "step": 17,
  "actor": "RED",
  "action_type": "exploit_vulnerability",
  "source_host": "host_03",
  "target_host": "host_07",
  "target_service": "api",
  "outcome": "success",
  "mitre_tactic": "Initial Access",
  "confidence": 0.91
}
```

### 10.2 `StateDelta`
```json
{
  "ts_ms": 1712412345680,
  "step": 17,
  "node_changes": [
    {"node_id": "host_07", "compromise_state": "compromised", "defense_state": "none"}
  ],
  "edge_changes": [
    {"edge_id": "host_03->host_07", "status": "active"}
  ]
}
```

### 10.3 `DetectionEvent`
```json
{
  "event_id": "det_000034",
  "ts_ms": 1712412345692,
  "step": 18,
  "detector": "BLUE",
  "target_host": "host_07",
  "signal": "traffic_spike",
  "severity": "high",
  "detected": true
}
```

### 10.4 `ExplainabilityRecord`
```json
{
  "ts_ms": 1712412345695,
  "step": 18,
  "action": "isolate_host",
  "target_host": "host_07",
  "confidence": 0.82,
  "reason_features": [
    {"name": "traffic_spike_ratio", "value": 3.1},
    {"name": "lateral_movement_pattern_match", "value": 0.77},
    {"name": "critical_asset_risk", "value": 0.88}
  ],
  "expected_effect": "contain lateral spread"
}
```

### 10.5 `ReplayManifest`
```json
{
  "replay_id": "replay_hero_01",
  "scenario_id": "scenario_unseen_web_rce",
  "seed": 1003,
  "checkpoint_id": "ckpt_blue_main_0009",
  "duration_steps": 200,
  "files": {
    "events": "events.jsonl",
    "topology": "topology_snapshots.json",
    "metrics": "metrics.json"
  }
}
```

### 10.6 `EvalReport`
```json
{
  "eval_id": "eval_20260404_001",
  "suite_id": "heldout_suite_v1",
  "kpis": {
    "damage_reduction_vs_no_defense": 0.33,
    "damage_reduction_vs_rule_based": 0.19,
    "detection_latency_improvement_vs_rule_based": 0.24
  },
  "per_scenario": []
}
```

## 11. Determinism Contract
- Eval replay determinism key: `(seed, scenario_id, checkpoint_id)`.
- For deterministic mode:
  - fixed RNG seeds in env generator and scripted Red policy.
  - deterministic event ordering in writer.
  - replay timestamps derived from step clock, not wall clock.
- Requirement:
  - repeated eval with identical key must produce byte-equal `events.jsonl` ordering and identical KPI aggregates.

## 12. Data & Artifact Contract

### 12.1 Replay Bundle Format
- `events.jsonl`: ordered `ActionEvent` + `DetectionEvent` + marker events.
- `topology_snapshots.json`: initial graph + diffs by step.
- `metrics.json`: time series for dashboard charts.
- `manifest.json`: metadata and integrity references.

### 12.2 Required Demo Assets
- `replay_hero_01` (used in scripted demo).
- `replay_alt_02`, `replay_alt_03`, `replay_alt_04` (backup choices).
- `eval_report_latest.json`.
- `checkpoint_blue_demo_best`.

## 13. Team Execution Plan (2-Track)

### 13.1 Track A (Krish) Responsibilities
- Environment simulator and policy interface.
- RL training pipeline.
- Eval harness and KPI computation.
- Replay generation pipeline.
- FastAPI endpoints + WebSocket streams.
- Explainability deterministic rationale engine.
- Ops scripts and Makefile.

### 13.2 Track B (Partner) Responsibilities
- Dashboard architecture and implementation.
- Cytoscape graph rendering and state transitions.
- Layer-1 chart panels.
- Layer-3 terminal log and explainability UI.
- Replay selector and run controls.
- Visual polish and presentation behavior.

### 13.3 Integration Freeze Checkpoints
- Checkpoint 1 (H+8): schema freeze (`ActionEvent`, `StateDelta`, `ExplainabilityRecord`).
- Checkpoint 2 (H+16): API freeze (all HTTP/WS endpoints implemented with stable payloads).
- Checkpoint 3 (H+28): demo freeze (hero replay loaded, full 3-layer sync proven).
- Checkpoint 4 (H+36): final acceptance run + fallback pack validation.

## 14. Setup & Ops (dgx0)

## 14.1 Verified Runtime Facts
- SSH:
  - `ssh -Y kgarg@chapman.edu@dgx0.chapman.edu`
- GPU:
  - A100 GPUs available and usable in Docker with `--gpus all`.
- Current tooling gap on dgx0:
  - `docker compose` plugin missing.
  - `uv` missing.

### 14.2 User-Only Manual Setup (Must Be Done By You)
- Install Docker Compose plugin:
```bash
sudo apt-get update
sudo apt-get install -y docker-compose-plugin
docker compose version
```
- Install `uv`:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
uv --version
```
- Confirm VPN and SSH access.
- Create SSH tunnel for dashboard access from local machine:
```bash
ssh -N \
  -L 3000:localhost:3000 \
  -L 8000:localhost:8000 \
  -L 5000:localhost:5000 \
  kgarg@chapman.edu@dgx0.chapman.edu
```

### 14.3 Required `.env` Contract
- Commit `.env.example`.
- Never commit `.env`.
- Required vars:
  - `CUDA_VISIBLE_DEVICES=5,6,7`
  - `PROJECT_NAME=pantherhacks`
  - `MLFLOW_TRACKING_URI=http://localhost:5000`
  - `API_PORT=8000`
  - `UI_PORT=3000`
  - `REPLAY_DIR=./artifacts/replays`

## 15. Docker Storage Safety Policy (Mandatory)
Context: DGX admin reported root disk risk due to Docker image buildup.

### 15.1 Policy
- Every project image/container/volume must include label:
  - `project=pantherhacks`
- No global prune in normal flow.
- Cleanup must be project-scoped.

### 15.2 Pre-Run Guardrail
```bash
df -h /
docker system df
```
- Do not run heavy pulls/training if root free space < 250GB.

### 15.3 Project-Scoped Cleanup Commands
```bash
# stop/remove project containers
docker ps -a --filter "label=project=pantherhacks" -q | xargs -r docker rm -f

# remove project images
docker images --filter "label=project=pantherhacks" -q | xargs -r docker rmi -f

# remove project volumes
docker volume ls --filter "label=project=pantherhacks" -q | xargs -r docker volume rm
```

### 15.4 Post-Demo Checklist
- Stop all project services.
- Export replay and report artifacts.
- Run project-scoped cleanup.
- Re-check `docker system df`.

## 16. Makefile Contract (Must Exist)
- `make bootstrap`
  - install Python deps via `uv`.
  - verify Docker, GPU access, env variables.
- `make up`
  - launch `api`, `ui`, `mlflow` stack via compose.
- `make train`
  - start Blue training job with GPUs `5,6,7`.
- `make eval`
  - execute held-out suite against best checkpoint and baselines.
- `make package-replays`
  - generate hero + 3 backup replay bundles.
- `make demo`
  - run stage-ready stack using pre-trained checkpoint and replay artifacts.
- `make down`
  - stop project services cleanly.

## 17. Testing Plan

### 17.1 Unit Tests
- topology generator constraints (host count, zones, service assignment).
- reward function correctness for known traces.
- MITRE tag mapping validity.
- explainability reason generation deterministic behavior.
- replay serializer deterministic ordering.

### 17.2 Integration Tests
- train job lifecycle API (`/train/run`, `/train/status`) works end-to-end.
- eval report generation API works with expected fields.
- replay bundle generation and loadability by UI.
- WebSocket event stream and reconnect behavior.

### 17.3 System/Demo Tests
- full stack boots with one command path.
- graph/log/metrics/explainability synchronized under replay.
- unseen attack scenario behaves as expected.
- fallback replay loads in under 5 seconds.

## 18. Demo Runbook (Stage Script)
1. Launch dashboard on hero replay baseline scenario.
2. Narrate weak defender outcome (fast compromise).
3. Switch to trained checkpoint replay, show KPI improvements.
4. Trigger unseen scenario replay, show adaptation and containment.
5. Run 20-30 second live stream burst.
6. Close with KPI panel and explainability evidence.

## 19. Risks & Mitigations
- Risk: GPU contention on shared server.
  - Mitigation: pre-trained checkpoint for stage path + fallback replay.
- Risk: Docker storage pressure.
  - Mitigation: label-based project cleanup policy + guardrail threshold.
- Risk: UI/backend schema drift.
  - Mitigation: freeze checkpoints and schema fixtures by H+8.
- Risk: unstable live training under timebox.
  - Mitigation: prioritize eval and replay quality over longer training.

## 20. Optional Portability Appendix (Keck)
- Keck cluster may require Apptainer rather than Docker.
- This PRD does not require Keck deployment for weekend success.
- If needed later, add Apptainer wrappers around the same artifact/API contracts.

## 21. Final Acceptance Checklist
- [x] Blue checkpoint exists and is demo-usable.
- [x] Eval report confirms KPI thresholds.
- [x] Hero + 3 replay bundles generated.
- [ ] 3-layer dashboard synchronized and polished.
- [x] Explainability panel active for Blue actions (Track A backend payload complete; Track B renders panel).
- [x] Live 20-30s burst works.
- [x] Disk hygiene cleanup completed post-demo.

Track B dependency: UI dashboard must consume Track A canonical run artifacts and replay/live stream contracts.
