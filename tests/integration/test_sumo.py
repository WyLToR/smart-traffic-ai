import csv
from pathlib import Path

import pytest

from smarttraffic_ai.config import Scenario, SignalConfig, load_scenario, project_root
from smarttraffic_ai.simulation import binary, build_network, run_simulation

try:
    binary("sumo")
    binary("netconvert")
    HAS_SUMO = True
except FileNotFoundError:
    HAS_SUMO = False

pytestmark = [pytest.mark.sumo, pytest.mark.skipif(not HAS_SUMO, reason="SUMO nem érhető el")]


@pytest.mark.parametrize("mode", ["fixed", "adaptive"])
def test_real_sumo_end_to_end(mode):
    root = project_root()
    network = build_network(root)
    assert network.is_file()
    scenario = load_scenario(root, "balanced")
    data = scenario.model_dump()
    data["duration"] = 120
    data["windows"][0]["end"] = 120
    scenario = type(scenario).model_validate(data)
    result = run_simulation(root, scenario, mode, SignalConfig())
    metrics = result["metrics"]
    assert metrics["arrived"] > 0
    assert metrics["demand"] == metrics["arrived"] + metrics["remaining"]
    assert metrics["remaining"] == metrics["pending"] + metrics["active_at_end"]
    assert metrics["mean_wait"] >= 0
    directory = Path(result["directory"])
    assert (directory / "tripinfo.xml").is_file()
    assert (directory / "result.json").is_file()
    with (directory / "timeline.csv").open(encoding="utf-8-sig") as stream:
        timeline = list(csv.DictReader(stream))
    assert len(timeline) == 120
    assert {row["phase"] for row in timeline} == {
        "NS_GREEN",
        "NS_YELLOW",
        "RED_TO_EW",
        "EW_GREEN",
        "EW_YELLOW",
        "RED_TO_NS",
    }
    assert max(int(row["queue"]) for row in timeline) > 0
    # A second connection after closing the first proves lifecycle cleanup.
    replay = run_simulation(root, scenario, mode, SignalConfig())
    assert replay["metrics"] == metrics
    assert replay["demand_sha256"] == result["demand_sha256"]


@pytest.mark.parametrize("mode", ["fixed", "adaptive"])
@pytest.mark.parametrize("rate", [0, 9000])
def test_empty_and_saturated_network(mode, rate):
    root = project_root()
    data = load_scenario(root, "balanced").model_dump()
    data["duration"] = 120
    data["windows"][0].update(end=120, rates={"N": rate, "S": 0, "E": 0, "W": 0})
    result = run_simulation(root, Scenario.model_validate(data), mode)
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
