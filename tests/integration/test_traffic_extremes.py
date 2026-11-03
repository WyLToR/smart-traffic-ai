import pytest

from smarttraffic_ai.config import Scenario, SearchConfig, load_scenario, project_root
from smarttraffic_ai.optimization import optimize
from smarttraffic_ai.simulation import binary, run_simulation

try:
    binary("sumo")
    HAS_SUMO = True
except FileNotFoundError:
    HAS_SUMO = False

pytestmark = [pytest.mark.sumo, pytest.mark.skipif(not HAS_SUMO, reason="SUMO nem érhető el")]


def scenario_with_rates(rates, duration=120):
    data = load_scenario(project_root(), "balanced").model_dump()
    data["duration"] = duration
    data["windows"][0].update(end=duration, rates=rates)
    return Scenario.model_validate(data)


@pytest.mark.parametrize("mode", ["fixed", "adaptive"])
@pytest.mark.parametrize("rate", [0, 9000])
def test_empty_and_saturated_network(mode, rate):
    scenario = scenario_with_rates({"N": rate, "S": 0, "E": 0, "W": 0})
    result = run_simulation(project_root(), scenario, mode)
    metrics = result["metrics"]
    assert metrics["collision_vehicle_events"] == 0
    assert metrics["demand"] == metrics["arrived"] + metrics["remaining"]
    if rate == 0:
        assert metrics["mean_wait"] == metrics["max_queue"] == metrics["demand"] == 0
        assert metrics["mean_travel_completed"] is None
    else:
        assert metrics["pending"] > 100
        assert metrics["total_insertion_delay"] > 0
        assert metrics["remaining"] > metrics["arrived"]


def test_optimizer_real_comparison():
    root = project_root()
    scenario = scenario_with_rates({"N": 850, "S": 850, "E": 200, "W": 200})
    report = optimize(root, scenario, SearchConfig(green_candidates=[15], seeds=[42, 73]))
    assert len(report["runs"]) == 6
    assert {row["controller"] for row in report["runs"]} == {"fixed", "adaptive"}
    assert all(row["collision_vehicle_events"] == 0 for row in report["runs"])
    assert report["best"]["score"] == min(row["score"] for row in report["summary"])
