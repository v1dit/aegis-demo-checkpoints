from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import orjson

from backend.app.core.config import settings
from backend.app.core.ids import prefixed_id
from backend.app.core.runs import read_checkpoint_payload, run_stage_dirs
from backend.app.core.state import shared_state
from backend.app.env.catalog import SERVICE_CATALOG, VULN_CATALOG
from backend.app.sandbox.launcher import DgxScriptLauncher, LocalThreadLauncher, SandboxLauncher
from backend.app.schemas.contracts import EpisodeSpec
from backend.app.schemas.topology import HostNode, NetworkEdge, TopologySnapshot, Vulnerability

SANDBOX_OBJECTIVES = ["exfiltrate", "lateral_move", "privilege_escalate", "persist"]
_run_counter = 0
_rate_limit_windows: dict[str, list[float]] = {}
_rate_lock = threading.Lock()
_vuln_service_lookup: dict[str, str] = {
    vuln_id: service for service, vuln_ids in VULN_CATALOG.items() for vuln_id in vuln_ids
}
_vuln_catalog = sorted(_vuln_service_lookup.keys())


class SandboxValidationError(ValueError):
    pass


class SandboxRateLimitError(RuntimeError):
    pass


class SandboxLiveUnavailableError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_run_id() -> str:
    global _run_counter
    _run_counter += 1
    return prefixed_id("run", _run_counter)


def _normalize_client_key(client_key: str | None) -> str:
    if not client_key:
        return "unknown"
    return client_key.split(",")[0].strip() or "unknown"


def _enforce_rate_limit(client_key: str) -> None:
    now = time.time()
    window = float(settings.sandbox_rate_limit_window_seconds)
    with _rate_lock:
        samples = _rate_limit_windows.setdefault(client_key, [])
        samples[:] = [sample for sample in samples if (now - sample) <= window]
        if len(samples) >= settings.sandbox_rate_limit_max_runs:
            raise SandboxRateLimitError("rate_limited")
        samples.append(now)


def _enforce_concurrency_limit(client_key: str) -> None:
    with shared_state.lock:
        active = [
            row
            for row in shared_state.sandbox_runs.values()
            if row.get("client_key") == client_key and row.get("status") in {"queued", "running"}
        ]
    if len(active) >= settings.sandbox_max_concurrent_per_client:
        raise SandboxRateLimitError("concurrency_limit_reached")


def _validate_episode_spec(spec: EpisodeSpec) -> None:
    if spec.defender_mode != "aegis":
        raise SandboxValidationError("defender_mode must be 'aegis'")
    if spec.horizon < settings.sandbox_min_horizon or spec.horizon > settings.sandbox_max_horizon:
        raise SandboxValidationError(
            "horizon must be between "
            f"{settings.sandbox_min_horizon} and {settings.sandbox_max_horizon}"
        )
    if len(spec.nodes) < 1 or len(spec.nodes) > settings.sandbox_max_nodes:
        raise SandboxValidationError(f"nodes must contain 1..{settings.sandbox_max_nodes} entries")

    node_ids = [node.id for node in spec.nodes]
    if len(set(node_ids)) != len(node_ids):
        raise SandboxValidationError("node IDs must be unique")
    node_id_set = set(node_ids)

    vuln_counts_by_node: dict[str, int] = {}
    for vuln in spec.vulnerabilities:
        if vuln.node_id not in node_id_set:
            raise SandboxValidationError(
                f"vulnerability references unknown node_id: {vuln.node_id}"
            )
        if vuln.vuln_id not in _vuln_service_lookup:
            raise SandboxValidationError(f"unknown vuln_id: {vuln.vuln_id}")
        vuln_counts_by_node[vuln.node_id] = vuln_counts_by_node.get(vuln.node_id, 0) + 1
        if vuln_counts_by_node[vuln.node_id] > settings.sandbox_max_vulns_per_node:
            raise SandboxValidationError(
                f"node {vuln.node_id} exceeds max vulnerabilities per node: "
                f"{settings.sandbox_max_vulns_per_node}"
            )

    if len(spec.red_objectives) > settings.sandbox_max_objectives:
        raise SandboxValidationError(
            f"red_objectives exceeds maximum: {settings.sandbox_max_objectives}"
        )

    for objective in spec.red_objectives:
        if objective.target_node_id not in node_id_set:
            raise SandboxValidationError(
                f"red objective references unknown target_node_id: {objective.target_node_id}"
            )
        if objective.objective not in SANDBOX_OBJECTIVES:
            raise SandboxValidationError(
                f"objective must be one of: {', '.join(SANDBOX_OBJECTIVES)}"
            )


def _role_to_zone(role: str | None) -> str:
    value = (role or "").lower()
    if "idp" in value or "identity" in value or "auth" in value:
        return "identity"
    if "saas" in value:
        return "saas"
    if "db" in value or "data" in value:
        return "data"
    if "admin" in value:
        return "admin"
    if "public" in value or "edge" in value:
        return "public"
    return "app"


def _role_to_asset_type(role: str | None) -> str:
    value = (role or "").lower()
    if "idp" in value or "identity" in value or "auth" in value:
        return "idp"
    if "saas" in value:
        return "crm_saas"
    if "integration" in value:
        return "integration_service"
    if "db" in value or "data" in value:
        return "data_store"
    if "endpoint" in value:
        return "endpoint"
    return "server"


def _node_services_and_vulns(
    spec: EpisodeSpec, node_id: str, severity: str
) -> tuple[list[str], list[Vulnerability]]:
    raw_vulns = [v for v in spec.vulnerabilities if v.node_id == node_id]
    services = sorted({_vuln_service_lookup[v.vuln_id] for v in raw_vulns})
    if not services:
        services = ["web", "api"]
    services = [service for service in services if service in SERVICE_CATALOG]
    if not services:
        services = ["web"]

    severity_rank = {"low": "low", "medium": "medium", "high": "high"}
    vulnerabilities = [
        Vulnerability(
            vuln_id=vuln.vuln_id,
            severity=severity_rank.get(severity, "medium"),
            service=_vuln_service_lookup[vuln.vuln_id],
        )
        for vuln in raw_vulns
    ]
    vulnerabilities = sorted(vulnerabilities, key=lambda value: (value.service, value.vuln_id))
    return services, vulnerabilities


def _build_topology(spec: EpisodeSpec, seed: int) -> TopologySnapshot:
    _ = seed
    nodes: list[HostNode] = []
    for node in spec.nodes:
        services, vulnerabilities = _node_services_and_vulns(spec, node.id, node.severity)
        nodes.append(
            HostNode(
                node_id=node.id,
                zone=_role_to_zone(node.role),
                asset_type=_role_to_asset_type(node.role),
                criticality=node.severity,
                services=services,
                vulnerabilities=vulnerabilities,
            )
        )

    edges: list[NetworkEdge] = []
    ordered_ids = [node.id for node in spec.nodes]
    for idx in range(max(0, len(ordered_ids) - 1)):
        source = ordered_ids[idx]
        target = ordered_ids[idx + 1]
        edges.append(NetworkEdge(edge_id=f"{source}->{target}", source=source, target=target))
    if len(ordered_ids) > 2:
        edges.append(
            NetworkEdge(
                edge_id=f"{ordered_ids[-1]}->{ordered_ids[0]}",
                source=ordered_ids[-1],
                target=ordered_ids[0],
            )
        )

    return TopologySnapshot(
        scenario_id="scenario_sandbox_custom",
        seed=seed,
        nodes=nodes,
        edges=edges,
    )


def _resolve_seed(spec: EpisodeSpec) -> int:
    if spec.seed is not None:
        return int(spec.seed)
    digest = hashlib.sha256(
        orjson.dumps(spec.model_dump(mode="json"), option=orjson.OPT_SORT_KEYS)
    ).hexdigest()
    return (int(digest[:8], 16) % 9000) + 1000


def _objective_priority(spec: EpisodeSpec) -> list[str]:
    ordered = sorted(
        spec.red_objectives,
        key=lambda row: int(row.priority or 0),
        reverse=True,
    )
    seen: set[str] = set()
    targets: list[str] = []
    for objective in ordered:
        if objective.target_node_id in seen:
            continue
        seen.add(objective.target_node_id)
        targets.append(objective.target_node_id)
    return targets


def _resolve_launcher() -> SandboxLauncher:
    if settings.sandbox_launcher.lower() == "dgx":
        script_path = (
            Path(__file__).resolve().parents[3] / "ops/scripts/dgx_enterprise_detached.sh"
        )
        return DgxScriptLauncher(
            script_path=script_path
        )
    return LocalThreadLauncher()


def _resolve_execution_mode() -> str:
    mode = settings.sandbox_execution_mode.lower()
    return "cluster" if mode == "cluster" else "local"


def _checkpoint_available(checkpoint_id: str) -> bool:
    return read_checkpoint_payload(checkpoint_id=checkpoint_id) is not None


def get_sandbox_readiness() -> dict[str, Any]:
    execution_mode = _resolve_execution_mode()
    checkpoint_id = str(settings.sandbox_checkpoint_id).strip()
    if not checkpoint_id:
        return {
            "execution_mode": execution_mode,
            "live_run_enabled": False,
            "live_block_reason": "live run unavailable: sandbox_checkpoint_id is not configured",
        }

    if execution_mode != "cluster":
        return {
            "execution_mode": execution_mode,
            "live_run_enabled": False,
            "live_block_reason": "live run unavailable: sandbox_execution_mode must be 'cluster'",
        }

    if not _checkpoint_available(checkpoint_id):
        return {
            "execution_mode": execution_mode,
            "live_run_enabled": False,
            "live_block_reason": (
                f"live run unavailable: checkpoint '{checkpoint_id}' was not found"
            ),
        }

    return {
        "execution_mode": execution_mode,
        "live_run_enabled": True,
        "live_block_reason": None,
    }


def get_sandbox_catalog() -> dict[str, Any]:
    readiness = get_sandbox_readiness()
    return {
        "vulnerabilities": _vuln_catalog,
        "objectives": SANDBOX_OBJECTIVES,
        "execution_mode": readiness["execution_mode"],
        "live_run_enabled": readiness["live_run_enabled"],
        "live_block_reason": readiness["live_block_reason"],
    }


def start_sandbox_run(*, episode_spec: EpisodeSpec, client_key: str | None) -> str:
    _validate_episode_spec(episode_spec)
    readiness = get_sandbox_readiness()
    if not readiness["live_run_enabled"]:
        raise SandboxLiveUnavailableError(str(readiness["live_block_reason"]))
    normalized_client_key = _normalize_client_key(client_key)
    _enforce_rate_limit(normalized_client_key)
    _enforce_concurrency_limit(normalized_client_key)

    run_id = _next_run_id()
    checkpoint_id = str(settings.sandbox_checkpoint_id).strip()
    stage_dirs = run_stage_dirs(run_id)
    sandbox_dir = stage_dirs["root"] / "sandbox"
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    artifact_paths = {
        "episode_spec": str(sandbox_dir / "episode_spec.json"),
        "events": str(sandbox_dir / "events.jsonl"),
        "summary": str(sandbox_dir / "summary.json"),
    }

    with shared_state.lock:
        shared_state.sandbox_runs[run_id] = {
            "run_id": run_id,
            "status": "queued",
            "client_key": normalized_client_key,
            "created_at": _utc_now(),
            "started_at": None,
            "ended_at": None,
            "error": None,
            "kpis": None,
            "cancel_requested": False,
            "timeout_exceeded": False,
            "episode_spec": episode_spec.model_dump(mode="json"),
            "artifact_paths": artifact_paths,
            "live_events": [],
            "checkpoint_id": checkpoint_id,
        }

    Path(artifact_paths["episode_spec"]).write_bytes(
        orjson.dumps(episode_spec.model_dump(mode="json"), option=orjson.OPT_INDENT_2)
    )

    thread = threading.Thread(
        target=_run_sandbox_job,
        args=(run_id,),
        daemon=True,
        name=f"sandbox-{run_id}",
    )
    thread.start()
    return run_id


def get_sandbox_status(run_id: str) -> dict[str, Any]:
    with shared_state.lock:
        run = shared_state.sandbox_runs.get(run_id)
    if run is None:
        raise KeyError(run_id)
    return {
        "run_id": run["run_id"],
        "status": run["status"],
        "created_at": run["created_at"],
        "started_at": run["started_at"],
        "ended_at": run["ended_at"],
        "kpis": run["kpis"],
        "error": run["error"],
        "artifact_paths": run.get("artifact_paths", {}),
    }


def request_sandbox_cancel(run_id: str) -> str:
    with shared_state.lock:
        run = shared_state.sandbox_runs.get(run_id)
        if run is None:
            raise KeyError(run_id)
        if run["status"] in {"completed", "failed", "cancelled"}:
            return str(run["status"])
        run["cancel_requested"] = True
        if run["status"] == "queued":
            run["status"] = "cancelled"
            run["ended_at"] = _utc_now()
    return "cancelled"


def sandbox_run_exists(run_id: str) -> bool:
    with shared_state.lock:
        return run_id in shared_state.sandbox_runs


def get_live_events(run_id: str, offset: int) -> tuple[list[dict[str, Any]], str | None]:
    with shared_state.lock:
        run = shared_state.sandbox_runs.get(run_id)
        if run is None:
            raise KeyError(run_id)
        events = list(run.get("live_events", [])[offset:])
        status = str(run["status"])
    return events, status


def _run_sandbox_job(run_id: str) -> None:
    with shared_state.lock:
        run = shared_state.sandbox_runs.get(run_id)
        if run is None:
            return
        if run.get("cancel_requested"):
            run["status"] = "cancelled"
            run["ended_at"] = _utc_now()
            return
        run["status"] = "running"
        run["started_at"] = _utc_now()
        episode_spec = EpisodeSpec.model_validate(run["episode_spec"])
        artifact_paths = dict(run["artifact_paths"])

    seed = _resolve_seed(episode_spec)
    topology = _build_topology(episode_spec, seed)
    prioritized_targets = _objective_priority(episode_spec)
    launcher = _resolve_launcher()
    checkpoint_id = str(run.get("checkpoint_id") or settings.sandbox_checkpoint_id).strip()

    events_path = Path(artifact_paths["events"])
    events_path.parent.mkdir(parents=True, exist_ok=True)

    with events_path.open("ab") as events_file:
        def emit(event_type: str, payload: dict[str, Any]) -> None:
            envelope_payload = dict(payload)
            if event_type == "action":
                if "action" not in envelope_payload and "action_type" in envelope_payload:
                    envelope_payload["action"] = envelope_payload["action_type"]
                if "target" not in envelope_payload and "target_host" in envelope_payload:
                    envelope_payload["target"] = envelope_payload["target_host"]
            envelope = {
                "type": event_type,
                "event_type": event_type,
                "payload": envelope_payload,
                "run_id": run_id,
            }
            with shared_state.lock:
                current = shared_state.sandbox_runs.get(run_id)
                if current is None:
                    return
                current["live_events"].append(envelope)
            events_file.write(orjson.dumps(envelope) + b"\n")
            events_file.flush()

        def should_stop() -> bool:
            with shared_state.lock:
                current = shared_state.sandbox_runs.get(run_id)
                if current is None:
                    return True
                if current.get("cancel_requested"):
                    return True
                started_at = current.get("started_at")
                if isinstance(started_at, str):
                    start_ts = datetime.fromisoformat(started_at).timestamp()
                    if (time.time() - start_ts) > settings.sandbox_run_timeout_seconds:
                        current["timeout_exceeded"] = True
                        return True
            return False

        try:
            result = launcher.run_episode(
                seed=seed,
                horizon=episode_spec.horizon,
                checkpoint_id=checkpoint_id,
                topology=topology,
                red_target_priority=prioritized_targets,
                event_callback=emit,
                should_stop=should_stop,
                step_delay_s=max(0.0, float(settings.sandbox_step_delay_seconds)),
            )

            kpis = {
                key: float(value)
                for key, value in asdict(result.summary).items()
                if isinstance(value, int | float)
            }

            with shared_state.lock:
                current = shared_state.sandbox_runs.get(run_id)
                if current is None:
                    return
                status = "completed"
                error = None
                if current.get("timeout_exceeded"):
                    status = "failed"
                    error = "sandbox_run_timed_out"
                elif current.get("cancel_requested"):
                    status = "cancelled"
                current.update(
                    {
                        "status": status,
                        "ended_at": _utc_now(),
                        "kpis": kpis,
                        "error": error,
                    }
                )

            summary_path = Path(artifact_paths["summary"])
            summary_payload = {
                "run_id": run_id,
                "status": get_sandbox_status(run_id)["status"],
                "seed": seed,
                "horizon": episode_spec.horizon,
                "scenario_id": result.scenario_id,
                "kpis": kpis,
            }
            summary_path.write_bytes(orjson.dumps(summary_payload, option=orjson.OPT_INDENT_2))
            emit("marker", {"status": get_sandbox_status(run_id)["status"]})
        except Exception as exc:  # pragma: no cover - defensive
            with shared_state.lock:
                current = shared_state.sandbox_runs.get(run_id)
                if current is None:
                    return
                current.update(
                    {
                        "status": "failed",
                        "ended_at": _utc_now(),
                        "error": str(exc),
                    }
                )
            emit("marker", {"status": "failed", "error": str(exc)})
