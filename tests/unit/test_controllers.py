import pytest
from pydantic import ValidationError

from smarttraffic_ai.config import SignalConfig
from smarttraffic_ai.controllers import ApproachController, Controller, signal_states


@pytest.mark.parametrize("approaches", [["N", "E", "S", "W"], ["N", "E", "W"]])
@pytest.mark.parametrize("mode", ["fixed", "adaptive"])
def test_protected_approach_service_has_safe_transitions_and_bounded_green(approaches, mode):
    cfg = SignalConfig(min_green=8, max_green=30, ns_green=13, ew_green=19)
    controller = ApproachController(cfg, approaches, mode)
    links = [[(f"in_{side}_0", "out_dummy_0", "")] for side in approaches]
    completed = []
    phase = controller.phase
    duration = 0
    for _ in range(800):
        state = controller.state(links)
        assert sum(char in "Gy" for char in state) <= 1
        if controller.phase == "ALL_RED":
            assert set(state) == {"r"}
        duration += 1
        controller.step_queues(dict.fromkeys(approaches, 50))
        if controller.phase != phase:
            if phase.endswith("GREEN"):
                assert cfg.min_green <= duration <= cfg.max_green
                if mode == "fixed":
                    expected = cfg.ns_green if phase[0] in "NS" else cfg.ew_green
                    assert duration == expected
            elif phase.endswith("YELLOW"):
                assert duration == cfg.yellow
            else:
                assert duration == cfg.all_red
            completed.append(phase)
            phase, duration = controller.phase, 0
    services = [p.split("_")[0] for p in completed if p.endswith("GREEN")]
    assert services[: len(approaches) * 2] == approaches * 2


EXPECTED_TRANSITIONS = {
    "NS_GREEN": "NS_YELLOW",
    "NS_YELLOW": "RED_TO_EW",
    "RED_TO_EW": "EW_GREEN",
    "EW_GREEN": "EW_YELLOW",
    "EW_YELLOW": "RED_TO_NS",
    "RED_TO_NS": "NS_GREEN",
}


@pytest.mark.parametrize("mode", ["fixed", "adaptive"])
@pytest.mark.parametrize(
    "queues", [(0, 0), (1000, 0), (0, 1000), (100, 100), (None, 1), (-1, 1), (float("nan"), 1)]
)
def test_safety_and_bounded_service(mode, queues):
    cfg = SignalConfig()
    control = Controller(cfg, mode)
    completed = []
    phase = control.phase
    duration = 0
    for _ in range(1000):
        duration += 1
        next_phase = control.step(*queues)
        if phase != next_phase:
            assert next_phase == EXPECTED_TRANSITIONS[phase]
            if phase.endswith("GREEN"):
                assert cfg.min_green <= duration <= cfg.max_green
            else:
                assert duration == (cfg.yellow if phase.endswith("YELLOW") else cfg.all_red)
            completed.append(phase)
            phase, duration = next_phase, 0
    assert completed.count("NS_GREEN") >= 5
    assert completed.count("EW_GREEN") >= 5


def test_signal_indices_are_not_hardcoded():
    links = [
        [(f"in_{a}_0", f"out_{b}_0", "")]
        for a, b in [("W", "E"), ("S", "N"), ("N", "S"), ("E", "W")]
    ]
    states = signal_states(links)
    assert states["NS_GREEN"] == "rGGr"
    assert states["EW_GREEN"] == "GrrG"
    assert states["RED_TO_EW"] == states["RED_TO_NS"] == "rrrr"
    for phase, state in states.items():
        assert not (state[0] in "Gy" and state[1] in "Gy")
    links[0] = [("in_W_0", "out_N_0", "")]
    with pytest.raises(ValueError):
        signal_states(links)


@pytest.mark.parametrize(
    "values", [{"ns_green": 2}, {"ew_green": 100}, {"yellow": 0}, {"min_green": 50}, {"all_red": 0}]
)
def test_invalid_signal_configuration(values):
    with pytest.raises(ValidationError):
        SignalConfig(**values)
