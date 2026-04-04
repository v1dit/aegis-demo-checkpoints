from __future__ import annotations

import random
from collections import defaultdict

from backend.app.env.catalog import SERVICE_CATALOG, VULN_CATALOG, ZONE_ORDER
from backend.app.schemas.topology import HostNode, NetworkEdge, TopologySnapshot, Vulnerability


def _sample_services(rng: random.Random) -> list[str]:
    count = rng.randint(1, 3)
    return sorted(rng.sample(SERVICE_CATALOG, k=count))


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
    count = host_count if host_count is not None else rng.randint(8, 20)

    nodes: list[HostNode] = []
    zone_buckets: dict[str, list[str]] = defaultdict(list)

    for index in range(count):
        node_id = f"host_{index + 1:02d}"
        zone = ZONE_ORDER[index % len(ZONE_ORDER)]
        services = _sample_services(rng)
        vulnerabilities = _sample_vulnerabilities(rng, services)
        nodes.append(
            HostNode(
                node_id=node_id,
                zone=zone,
                services=services,
                vulnerabilities=vulnerabilities,
            )
        )
        zone_buckets[zone].append(node_id)

    edges: dict[str, NetworkEdge] = {}

    for zone in ZONE_ORDER:
        hosts = sorted(zone_buckets[zone])
        for idx in range(len(hosts) - 1):
            source = hosts[idx]
            target = hosts[idx + 1]
            edge_id = f"{source}->{target}"
            edges[edge_id] = NetworkEdge(edge_id=edge_id, source=source, target=target)

    for idx in range(len(ZONE_ORDER) - 1):
        src_zone = ZONE_ORDER[idx]
        dst_zone = ZONE_ORDER[idx + 1]
        src = sorted(zone_buckets[src_zone])[0]
        dst = sorted(zone_buckets[dst_zone])[0]
        edge_id = f"{src}->{dst}"
        edges[edge_id] = NetworkEdge(edge_id=edge_id, source=src, target=dst)

    for _ in range(max(1, count // 4)):
        src, dst = rng.sample([node.node_id for node in nodes], k=2)
        edge_id = f"{src}->{dst}"
        edges.setdefault(edge_id, NetworkEdge(edge_id=edge_id, source=src, target=dst))

    return TopologySnapshot(
        scenario_id=scenario_id,
        seed=seed,
        nodes=sorted(nodes, key=lambda n: n.node_id),
        edges=sorted(edges.values(), key=lambda e: e.edge_id),
    )
