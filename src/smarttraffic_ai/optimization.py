from __future__ import annotations

from collections import defaultdict
from itertools import product
from pathlib import Path
from statistics import mean
from typing import Callable

from smarttraffic_ai.config import Scenario, SearchConfig, SignalConfig, load_yaml
from smarttraffic_ai.simulation import output_directory, run_simulation, save_csv, save_json


def objective(metrics: dict, settings: SearchConfig) -> float:
    return (
        metrics["mean_wait"]
        + settings.max_wait_weight * metrics["max_wait"]
        + settings.remaining_weight * metrics["remaining"] / max(1, metrics["demand"])
    )


def summarize(rows: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for row in rows:
        groups[row["candidate"]].append(row)
    summary = []
    for name, group in groups.items():
        summary.append(
            {
                "candidate": name,
                "controller": group[0]["controller"],
                "ns_green": group[0]["ns_green"],
                "ew_green": group[0]["ew_green"],
                **{
                    key: mean(row[key] for row in group)
                    for key in (
                        "score",
                        "mean_wait",
                        "max_wait",
                        "mean_queue",
                        "arrived",
                        "remaining",
                    )
                },
                "runs": len(group),
            }
        )
    return sorted(summary, key=lambda row: (row["score"], row["candidate"]))


def optimize(
    root: Path,
    scenario: Scenario,
    settings: SearchConfig | None = None,
    runner: Callable = run_simulation,
) -> dict:
    settings = settings or load_yaml(root / "config/optimization.yaml", SearchConfig)
    base = load_yaml(root / "config/simulation.yaml", SignalConfig)
    candidates = [("fixed-baseline", "fixed", base), ("adaptive", "adaptive", base)]
    for ns, ew in product(settings.green_candidates, repeat=2):
        # Validate the entire search before starting any expensive simulation.
        cfg = SignalConfig.model_validate({**base.model_dump(), "ns_green": ns, "ew_green": ew})
        if (ns, ew) != (base.ns_green, base.ew_green):
            candidates.append((f"fixed-{ns}-{ew}", "fixed", cfg))
    directory = output_directory(root, "optimization")
    rows = []
    for name, mode, cfg in candidates:
        for seed in dict.fromkeys(settings.seeds):
            result = runner(root, scenario, mode=mode, config=cfg, seed=seed)
            rows.append(
                {
                    "candidate": name,
                    "controller": mode,
                    "seed": seed,
                    "ns_green": cfg.ns_green,
                    "ew_green": cfg.ew_green,
                    "score": objective(result["metrics"], settings),
                    **result["metrics"],
                    "run_directory": result["directory"],
                    "demand_sha256": result["demand_sha256"],
                    "network_sha256": result["network_sha256"],
                }
            )
            save_csv(directory / "runs.csv", rows)
    for seed in dict.fromkeys(settings.seeds):
        selected = [row for row in rows if row["seed"] == seed]
        if len({row["demand_sha256"] for row in selected}) != 1:
            raise ValueError("A jelöltek forgalmi igénye eltér; az összehasonlítás érvénytelen.")
        if len({row["network_sha256"] for row in selected}) != 1:
            raise ValueError("A jelöltek hálózata eltér; az összehasonlítás érvénytelen.")
    summary = summarize(rows)
    report = {
        "scenario": scenario.model_dump(),
        "settings": settings.model_dump(),
        "best": summary[0],
        "summary": summary,
        "runs": rows,
        "directory": str(directory),
    }
    save_csv(directory / "comparison.csv", summary)
    save_json(directory / "comparison.json", report)
    return report
