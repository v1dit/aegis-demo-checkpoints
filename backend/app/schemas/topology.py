from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Zone = Literal["public", "app", "data", "admin", "identity", "saas"]
AssetType = Literal[
    "endpoint",
    "server",
    "idp",
    "crm_saas",
    "integration_service",
    "data_store",
]
Criticality = Literal["low", "medium", "high", "critical"]


class Vulnerability(BaseModel):
    vuln_id: str
    severity: Literal["low", "medium", "high", "critical"]
    service: str


class HostNode(BaseModel):
    node_id: str
    zone: Zone
    asset_type: AssetType = "server"
    criticality: Criticality = "medium"
    services: list[str] = Field(default_factory=list)
    vulnerabilities: list[Vulnerability] = Field(default_factory=list)


class NetworkEdge(BaseModel):
    edge_id: str
    source: str
    target: str
    status: Literal["active", "blocked"] = "active"
    edge_type: Literal["network", "identity_trust", "api_integration", "privileged_access"] = (
        "network"
    )


class TopologySnapshot(BaseModel):
    scenario_id: str
    seed: int
    nodes: list[HostNode]
    edges: list[NetworkEdge]
