import pytest
from pydantic import ValidationError

from smarttraffic_ai.config import Scenario, load_scenario, project_root
from smarttraffic_ai.traffic import generate_demand


@pytest.mark.parametrize("name", ["balanced", "rush-hour", "variable"])
def test_scenarios_reproducible(name):
    scenario = load_scenario(project_root(), name)
    demand = generate_demand(scenario, 42)
    assert demand == generate_demand(scenario, 42)
    assert demand != generate_demand(scenario, 73)
    assert len(demand) > 200
    assert all(0 <= v.depart < scenario.duration for v in demand)
    assert len({v.id for v in demand}) == len(demand)


@pytest.mark.parametrize("rate", [0, 0.1, 9000])
def test_zero_low_and_overloaded_demand(rate):
    data = load_scenario(project_root(), "balanced").model_dump()
    data["windows"][0]["rates"] = {"N": rate, "S": 0, "E": 0, "W": 0}
    demand = generate_demand(Scenario.model_validate(data), 42)
    assert all(v.direction == "N" for v in demand)
    if rate == 0:
        assert demand == []


@pytest.mark.parametrize("change", ["missing", "negative", "gap", "end"])
def test_invalid_scenario(change):
    data = load_scenario(project_root(), "balanced").model_dump()
    if change == "missing":
        del data["windows"][0]["rates"]["N"]
    elif change == "negative":
        data["windows"][0]["rates"]["N"] = -1
    elif change == "gap":
        data["windows"][0]["begin"] = 1
    else:
        data["duration"] = 10
    with pytest.raises(ValidationError):
        Scenario.model_validate(data)
