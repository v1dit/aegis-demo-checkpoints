from __future__ import annotations

import random
from collections import defaultdict

from backend.app.env.catalog import (
    ASSET_SERVICE_CATALOG,
    ENTERPRISE_ZONE_ORDER,
    SERVICE_CATALOG,
    VULN_CATALOG,
    ZONE_ORDER,
)
from backend.app.schemas.topology import HostNode, NetworkEdge, TopologySnapshot, Vulnerability


def _is_enterprise_scenario(scenario_id: str) -> bool:
    return scenario_id.startswith("scenario_enterprise_")


def _asset_type_for_zone(rng: random.Random, zone: str) -> str:
    by_zone = {
        "public": ["endpoint", "server"],
        "app": ["server", "integration_service"],
        "data": ["data_store", "server"],
        "admin": ["server"],
        "identity": ["idp"],
        "saas": ["crm_saas", "integration_service"],
    }
    candidates = by_zone.get(zone, ["server"])
    return candidates[rng.randint(0, len(candidates) - 1)]


def _criticality_for_zone(zone: str) -> str:
    if zone in {"identity", "saas"}:
        return "critical"
    if zone == "data":
        return "high"
    if zone == "admin":
        return "medium"
    return "low"


def _sample_services(rng: random.Random, asset_type: str) -> list[str]:
    candidates = ASSET_SERVICE_CATALOG.get(asset_type, SERVICE_CATALOG)
    count = min(len(candidates), rng.randint(1, 3))
    return sorted(rng.sample(candidates, k=count))


def _sample_vulnerabilities(rng: random.Random, services: list[str]) -> list[Vulnerability]:
    vulns: list[Vulnerability] = []
    severities = ["low", "medium", "high", "critical"]
    for service in services:
        options = VULN_CATALOG[service]
        sample_size = 1 if rng.random() < 0.7 else min(2, len(options))
        for vuln_id in rng.sample(options, k=sample_size):
            severity_seed = sum(ord(char) for char in vuln_id)
            severity = severities[(severity_seed + rng.randint(0, 3)) % len(severities)]
            vulns.append(Vulnerability(vuln_id=vuln_id, severity=severity, service=service))
    return sorted(vulns, key=lambda v: (v.service, v.vuln_id))


def generate_topology(
    seed: int,
    scenario_id: str,
    host_count: int | None = None,
) -> TopologySnapshot:
    rng = random.Random(seed)
    enterprise = _is_enterprise_scenario(scenario_id)
    if host_count is not None:
        count = host_count
    else:
        count = rng.randint(35, 60) if enterprise else rng.randint(8, 20)
    zone_order = ENTERPRISE_ZONE_ORDER if enterprise else ZONE_ORDER

    nodes: list[HostNode] = []
    zone_buckets: dict[str, list[str]] = defaultdict(list)

    for index in range(count):
        node_id = f"host_{index + 1:02d}"
        zone = zone_order[index % len(zone_order)]
        asset_type = _asset_type_for_zone(rng, zone)
        services = _sample_services(rng, asset_type)
        vulnerabilities = _sample_vulnerabilities(rng, services)
        nodes.append(
            HostNode(
                node_id=node_id,
                zone=zone,
                asset_type=asset_type,
                criticality=_criticality_for_zone(zone),
                services=services,
                vulnerabilities=vulnerabilities,
            )
        )
        zone_buckets[zone].append(node_id)

    edges: dict[str, NetworkEdge] = {}

    for zone in zone_order:
        hosts = sorted(zone_buckets[zone])
        for idx in range(len(hosts) - 1):
            source = hosts[idx]
            target = hosts[idx + 1]
            edge_id = f"{source}->{target}"
            edges[edge_id] = NetworkEdge(
                edge_id=edge_id,
                source=source,
                target=target,
                edge_type="network",
            )

    for idx in range(len(zone_order) - 1):
        src_zone = zone_order[idx]
        dst_zone = zone_order[idx + 1]
        src = sorted(zone_buckets[src_zone])[0]
        dst = sorted(zone_buckets[dst_zone])[0]
        edge_id = f"{src}->{dst}"
        edges[edge_id] = NetworkEdge(edge_id=edge_id, source=src, target=dst, edge_type="network")

    for _ in range(max(1, count // 4)):
        src, dst = rng.sample([node.node_id for node in nodes], k=2)
        edge_id = f"{src}->{dst}"
        edges.setdefault(
            edge_id,
            NetworkEdge(edge_id=edge_id, source=src, target=dst, edge_type="network"),
        )

    if enterprise:
        identity_hosts = sorted(zone_buckets["identity"])
        saas_hosts = sorted(zone_buckets["saas"])
        app_hosts = sorted(zone_buckets["app"])
        admin_hosts = sorted(zone_buckets["admin"])

        if identity_hosts and saas_hosts:
            idp_host = identity_hosts[0]
            for saas_host in saas_hosts[: max(1, len(saas_hosts) // 2)]:
                edge_id = f"{idp_host}->{saas_host}"
                edges[edge_id] = NetworkEdge(
                    edge_id=edge_id,
                    source=idp_host,
                    target=saas_host,
                    edge_type="identity_trust",
                )

        if app_hosts and saas_hosts:
            for app_host in app_hosts[: max(1, len(app_hosts) // 2)]:
                saas_host = saas_hosts[rng.randint(0, len(saas_hosts) - 1)]
                edge_id = f"{app_host}->{saas_host}"
                edges[edge_id] = NetworkEdge(
                    edge_id=edge_id,
                    source=app_host,
                    target=saas_host,
                    edge_type="api_integration",
                )

        if admin_hosts and identity_hosts:
            admin = admin_hosts[0]
            idp_host = identity_hosts[0]
            edge_id = f"{admin}->{idp_host}"
            edges[edge_id] = NetworkEdge(
                edge_id=edge_id,
                source=admin,
                target=idp_host,
                edge_type="privileged_access",
            )

    return TopologySnapshot(
        scenario_id=scenario_id,
        seed=seed,
        nodes=sorted(nodes, key=lambda n: n.node_id),
        edges=sorted(edges.values(), key=lambda e: e.edge_id),
    )
