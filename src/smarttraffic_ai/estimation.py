from __future__ import annotations

import math

from smarttraffic_ai.config import Scenario, Window
from smarttraffic_ai.detection import MOTOR_VEHICLES, DetectionResult


def estimate_scenarios(
    observation: DetectionResult, prior_rate: float = 450, duration: int = 600
) -> tuple[dict, list[Scenario]]:
    """Visible counts are occupancy observations, not measured arrival rates."""
    if not math.isfinite(prior_rate) or not 0 <= prior_rate <= 5000:
        raise ValueError("A feltételezett intenzitás 0 és 5000 jármű/óra közé essen.")
    counts = observation.summary()["by_direction"]
    visible = {
        r.direction
        for r in observation.objects
        if r.direction is not None and r.category in MOTOR_VEHICLES
    }
    assumptions = [
        "Állóképi darabszámok; a sebesség, sorhossz és érkezés nincs mérve.",
        f"Feltételezett érkezés: {prior_rate} jármű/óra/irány; szorzók: 0,5 / 1 / 1,5.",
        "Minden irány ugyanazt az intenzitást kapja; a hálózat kezdetben üres.",
    ]
    estimate = {
        "source_id": observation.source_id,
        "timestamp": observation.timestamp.isoformat(),
        "source": observation.source,
        "observed_counts": counts,
        "unobserved_or_empty_directions": [d for d in ("N", "S", "E", "W") if d not in visible],
        "uncertainty": "Magas; a sorhossz, sebesség és érkezési intenzitás nem mérhető.",
        "assumed_arrival_rate": prior_rate,
        "assumptions": assumptions,
    }
    scenarios = []
    for name, factor, label in [
        ("low", 0.5, "Alacsony"),
        ("medium", 1, "Közepes"),
        ("high", 1.5, "Magas"),
    ]:
        scenarios.append(
            Scenario(
                id=f"estimated-{name}",
                name=f"{label} feltételezett intenzitás",
                duration=duration,
                source="mock-estimate" if observation.source == "mock" else "image-estimate",
                assumptions=assumptions
                + [f"Megfigyelés: {observation.source_id}; darabszámok: {counts}"],
                windows=[
                    Window(
                        begin=0,
                        end=duration,
                        rates={d: prior_rate * factor for d in ("N", "S", "E", "W")},
                    )
                ],
            )
        )
    return estimate, scenarios
