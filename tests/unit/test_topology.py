from backend.app.env.topology import generate_topology


def test_topology_constraints_and_zones() -> None:
    topology = generate_topology(seed=42, scenario_id="scenario_test")

    assert 8 <= len(topology.nodes) <= 20
    zones = {node.zone for node in topology.nodes}
    assert zones == {"public", "app", "data", "admin"}

    for node in topology.nodes:
        assert node.services
        assert node.vulnerabilities



def test_topology_is_deterministic_for_same_seed() -> None:
    first = generate_topology(seed=2026, scenario_id="scenario_test").model_dump(mode="json")
    second = generate_topology(seed=2026, scenario_id="scenario_test").model_dump(mode="json")
    assert first == second


def test_enterprise_topology_has_extended_surface() -> None:
    topology = generate_topology(seed=404, scenario_id="scenario_enterprise_crm_identity_chain_v1")

    assert 35 <= len(topology.nodes) <= 60

    zones = {node.zone for node in topology.nodes}
    assert {"identity", "saas"}.issubset(zones)

    asset_types = {node.asset_type for node in topology.nodes}
    assert {"idp", "crm_saas", "integration_service"}.issubset(asset_types)

    trust_edges = [edge for edge in topology.edges if edge.edge_type != "network"]
    assert trust_edges
