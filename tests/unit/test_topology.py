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
