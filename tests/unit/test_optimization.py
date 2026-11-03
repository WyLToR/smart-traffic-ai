import shutil

import pytest

from smarttraffic_ai.config import SearchConfig, load_scenario, project_root
from smarttraffic_ai.optimization import objective, optimize, summarize


def test_objective_penalizes_unserved_vehicles():
    cfg = SearchConfig(green_candidates=[15], seeds=[42])
    served = {"mean_wait": 10, "max_wait": 20, "remaining": 0, "demand": 100}
    starved = {"mean_wait": 0, "max_wait": 0, "remaining": 100, "demand": 100}
    assert objective(served, cfg) < objective(starved, cfg)


def test_best_is_chosen_from_mean_of_seeds():
    rows = []
    for candidate, scores in {"a": [1, 99], "b": [30, 30]}.items():
        for score in scores:
            rows.append(
                {
                    "candidate": candidate,
                    "controller": "fixed",
                    "score": score,
                    "ns_green": 25,
                    "ew_green": 25,
                    "mean_wait": score,
                    "max_wait": score,
                    "mean_queue": 1,
                    "arrived": 10,
                    "remaining": 2,
                }
            )
    assert summarize(rows)[0]["candidate"] == "b"


def test_optimizer_uses_same_seeds_and_safe_candidates(tmp_path):
    calls = []

    def fake_runner(root, scenario, mode, config, seed):
        calls.append((mode, config, seed))
        return {
            "metrics": {
                "demand": 10,
                "mean_wait": 2,
                "max_wait": 3,
                "mean_queue": 1,
                "arrived": 8,
                "remaining": 2,
            },
            "directory": "test-only",
            "demand_sha256": str(seed),
            "network_sha256": "same",
        }

    root = project_root()
    scenario = load_scenario(root, "balanced")
    shutil.copytree(root / "config", tmp_path / "config")
    report = optimize(
        tmp_path,
        scenario,
        SearchConfig(green_candidates=[15, 35], seeds=[42, 73]),
        fake_runner,
    )
    assert len(calls) == 12
    assert all(c.min_green <= c.ns_green <= c.max_green for _, c, _ in calls)
    assert all(row["runs"] == 2 for row in report["summary"])


def test_invalid_candidates_fail_before_any_simulation():
    def forbidden(*args, **kwargs):
        pytest.fail("Hibás keresési tér nem indíthat szimulációt.")

    root = project_root()
    with pytest.raises(ValueError):
        optimize(
            root,
            load_scenario(root, "balanced"),
            SearchConfig(green_candidates=[1], seeds=[42]),
            forbidden,
        )
