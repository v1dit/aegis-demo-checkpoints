from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Actor = Literal["RED", "BLUE", "ENV"]
RedActionType = Literal[
    "scan_host",
    "enumerate_service",
    "exploit_vulnerability",
    "lateral_move",
    "privilege_escalate",
    "exfiltrate_data",
]
BlueActionType = Literal[
    "monitor_host",
    "patch_service",
    "isolate_host",
    "block_connection",
    "rotate_credentials",
    "deploy_deception",
]
ActionType = RedActionType | BlueActionType | Literal["step_marker"]
MitreTactic = Literal[
    "Reconnaissance",
    "Initial Access",
    "Execution",
    "Lateral Movement",
    "Credential Access",
    "Exfiltration",
    "Defense Evasion",
]


class TrainRunRequest(BaseModel):
    run_name: str
    seed: int
    gpu_ids: list[int]
    max_timesteps: int = Field(ge=1)
    config_profile: str
    fresh_start: bool = False
    run_id: str | None = None


class TrainRunResponse(BaseModel):
    run_id: str
    status: Literal["started"]
    parent_run_id: str | None = None
    parent_checkpoint: str | None = None


class TrainStatusResponse(BaseModel):
    run_id: str
    status: Literal["queued", "running", "completed", "failed"]
    phase: str
    timesteps: int
    parent_run_id: str | None = None
    parent_checkpoint: str | None = None
    checkpoint_path: str | None = None
    learning_metrics: dict[str, float] = Field(default_factory=dict)


class EvalRunRequest(BaseModel):
    checkpoint_id: str
    suite_id: str
    seeds: list[int]
    run_id: str | None = None


class EvalRunResponse(BaseModel):
    eval_id: str
    status: Literal["started"]
    run_id: str


class FeatureValue(BaseModel):
    name: str
    value: float


class ActionEvent(BaseModel):
    event_id: str
    ts_ms: int
    step: int
    actor: Actor
    action_type: ActionType
    source_host: str
    target_host: str
    target_service: str | None = None
    outcome: str
    mitre_tactic: MitreTactic
    confidence: float


class NodeChange(BaseModel):
    node_id: str
    compromise_state: Literal["neutral", "compromised"]
    defense_state: Literal["none", "hardened", "isolated", "monitored", "deception"]


class EdgeChange(BaseModel):
    edge_id: str
    status: Literal["active", "blocked"]


class StateDelta(BaseModel):
    ts_ms: int
    step: int
    node_changes: list[NodeChange]
    edge_changes: list[EdgeChange]


class DetectionEvent(BaseModel):
    event_id: str
    ts_ms: int
    step: int
    detector: Literal["BLUE"]
    target_host: str
    signal: str
    severity: Literal["low", "medium", "high"]
    detected: bool


class ExplainabilityRecord(BaseModel):
    ts_ms: int
    step: int
    action: BlueActionType
    target_host: str
    confidence: float
    reason_features: list[FeatureValue]
    expected_effect: str


class ReplayFiles(BaseModel):
    events: str
    topology: str
    metrics: str


class ReplayManifest(BaseModel):
    replay_id: str
    scenario_id: str
    seed: int
    checkpoint_id: str
    duration_steps: int
    files: ReplayFiles


class EvalKpis(BaseModel):
    damage_reduction_vs_no_defense: float
    damage_reduction_vs_rule_based: float
    detection_latency_improvement_vs_rule_based: float
    exfiltration_prevention_rate: float | None = None
    critical_asset_compromise_rate: float | None = None


class PerScenarioEval(BaseModel):
    scenario_id: str
    seed: int
    blue_damage: float
    no_defense_damage: float
    rule_based_damage: float
    blue_detection_latency: float
    rule_based_detection_latency: float


class EvalReport(BaseModel):
    eval_id: str
    suite_id: str
    run_id: str | None = None
    kpis: EvalKpis
    per_scenario: list[PerScenarioEval]
    improvement_delta_vs_parent: dict[str, float] | None = None


class ReplayListItem(BaseModel):
    replay_id: str
    scenario_id: str
    checkpoint_id: str
    seed: int


class ReplayListResponse(BaseModel):
    run_id: str | None = None
    replays: list[ReplayListItem]


class ReplayBundleResponse(BaseModel):
    run_id: str | None = None
    replay_id: str
    bundle_dir: str
    manifest: ReplayManifest
    files: dict[str, str]


class RunListItem(BaseModel):
    run_id: str
    created_at: str | None = None
    updated_at: str | None = None
    train_status: str
    eval_status: str
    replay_status: str
    replay_count: int


class RunListResponse(BaseModel):
    runs: list[RunListItem]


SandboxRunStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


class EpisodeNode(BaseModel):
    id: str
    severity: Literal["low", "medium", "high"]
    role: str | None = None


class EpisodeVulnerability(BaseModel):
    node_id: str
    vuln_id: str
    exploitability: float | None = Field(default=None, ge=0.0, le=1.0)


class RedObjective(BaseModel):
    target_node_id: str
    objective: str
    priority: int | None = None


class EpisodeSpec(BaseModel):
    name: str
    seed: int | None = None
    horizon: int = Field(ge=1)
    nodes: list[EpisodeNode]
    vulnerabilities: list[EpisodeVulnerability] = Field(default_factory=list)
    red_objectives: list[RedObjective] = Field(default_factory=list)
    defender_mode: Literal["aegis"] = "aegis"


class SandboxRunCreateRequest(BaseModel):
    episode_spec: EpisodeSpec


class SandboxRunCreateResponse(BaseModel):
    run_id: str
    status: Literal["queued"]
    stream_url: str


class SandboxRunStatusResponse(BaseModel):
    run_id: str
    status: SandboxRunStatus
    created_at: str
    started_at: str | None = None
    ended_at: str | None = None
    kpis: dict[str, float] | None = None
    error: str | None = None
    artifact_paths: dict[str, str] = Field(default_factory=dict)


class SandboxCancelResponse(BaseModel):
    run_id: str
    status: SandboxRunStatus


class SandboxCatalogResponse(BaseModel):
    vulnerabilities: list[str]
    objectives: list[str]


class StreamEvent(BaseModel):
    event_type: Literal["action", "detection", "state_delta", "explainability", "metric", "marker"]
    payload: dict[str, Any]
