from __future__ import annotations

import random
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from smarttraffic_ai.config import Scenario

OPPOSITE = {"N": "S", "S": "N", "E": "W", "W": "E"}


@dataclass(frozen=True)
class Demand:
    id: str
    depart: int
    direction: str


def generate_demand(scenario: Scenario, seed: int) -> list[Demand]:
    """Explicit Poisson demand; no controller-dependent random draws."""
    rng = random.Random(seed)
    events = []
    for window in scenario.windows:
        for direction in OPPOSITE:
            rate = window.rates[direction]
            if rate == 0:
                continue
            time = window.begin + rng.expovariate(rate / 3600)
            while time < window.end:
                events.append((int(time), direction))
                time += rng.expovariate(rate / 3600)
    events.sort()
    return [Demand(f"v{i}", time, direction) for i, (time, direction) in enumerate(events)]


def write_xml(element: ET.Element, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(element)
    ET.ElementTree(element).write(path, encoding="utf-8", xml_declaration=True)


def write_routes(demand: list[Demand], path: Path):
    root = ET.Element("routes")
    ET.SubElement(root, "vType", id="car", vClass="passenger", sigma="0.5")
    for direction, opposite in OPPOSITE.items():
        ET.SubElement(root, "route", id=direction, edges=f"in_{direction} out_{opposite}")
    for vehicle in demand:
        ET.SubElement(
            root,
            "vehicle",
            id=vehicle.id,
            type="car",
            route=vehicle.direction,
            depart=str(vehicle.depart),
            departLane="0",
            departSpeed="0",
        )
    write_xml(root, path)
