from __future__ import annotations

import math
from typing import Literal, Protocol

from smarttraffic_ai.config import SignalConfig

PHASES = ("NS_GREEN", "NS_YELLOW", "RED_TO_EW", "EW_GREEN", "EW_YELLOW", "RED_TO_NS")


class TrafficController(Protocol):
    phase: str

    def step(self, ns_queue: float | None, ew_queue: float | None) -> str: ...


def signal_states(controlled_links) -> dict[str, str]:
    """Derive indices from SUMO, reject unknown or non-straight links."""
    groups = []
    opposite = {"N": "S", "S": "N", "E": "W", "W": "E"}
    directions = []
    for links in controlled_links:
        if len(links) != 1:
            raise ValueError("Csak egyértelmű, egyenes sávkapcsolatok támogatottak.")
        incoming, outgoing, _ = links[0]
        direction = incoming.removeprefix("in_").removesuffix("_0")
        if direction not in opposite or outgoing != f"out_{opposite[direction]}_0":
            raise ValueError("Ismeretlen vagy kanyarodó kapcsolat a hálózatban.")
        directions.append(direction)
        groups.append("NS" if direction in "NS" else "EW")
    if len(directions) != 4 or set(directions) != set(opposite):
        raise ValueError("Pontosan négy egyenes kapcsolat szükséges.")
    states = {}
    for phase in PHASES:
        group = phase[:2]
        char = "G" if phase.endswith("GREEN") else "y"
        states[phase] = "".join(char if g == group else "r" for g in groups)
    return states


class Controller:
    def __init__(self, config: SignalConfig, mode: Literal["fixed", "adaptive"] = "fixed"):
        if mode not in {"fixed", "adaptive"}:
            raise ValueError("Ismeretlen vezérlő: fixed vagy adaptive szükséges.")
        self.config = config
        self.mode = mode
        self.phase = PHASES[0]
        self.elapsed = 0

    def step(self, ns_queue: float | None, ew_queue: float | None) -> str:
        self.elapsed += 1
        cfg = self.config
        if self.phase.endswith("GREEN"):
            duration = cfg.ns_green if self.phase.startswith("NS") else cfg.ew_green
            valid = all(
                isinstance(q, (float, int)) and math.isfinite(q) and q >= 0
                for q in (ns_queue, ew_queue)
            )
            if self.mode == "adaptive" and valid:
                active, other = (
                    (ns_queue, ew_queue) if self.phase.startswith("NS") else (ew_queue, ns_queue)
                )
                target = min(cfg.max_green, cfg.min_green + 2 * active)
                finish = self.elapsed >= cfg.max_green or (
                    self.elapsed >= cfg.min_green
                    and other > 0
                    and (active == 0 or self.elapsed >= target)
                )
            else:
                finish = self.elapsed >= duration
        else:
            duration = cfg.yellow if self.phase.endswith("YELLOW") else cfg.all_red
            finish = self.elapsed >= duration
        if finish:
            self.phase = PHASES[(PHASES.index(self.phase) + 1) % len(PHASES)]
            self.elapsed = 0
        return self.phase


class ApproachController:
    """Reuse green-time decisions, serving one approach at a time for protected turns."""

    def __init__(self, config: SignalConfig, approaches, mode="fixed"):
        self.config = config
        self.approaches = list(approaches)
        self.index = 0
        self.controller = Controller(config, mode)
        self._configure_green()

    def _configure_green(self):
        duration = self.config.ns_green if self.direction in {"N", "S"} else self.config.ew_green
        self.controller.config = self.config.model_copy(
            update={"ns_green": duration, "ew_green": duration}
        )

    @property
    def direction(self):
        return self.approaches[self.index]

    @property
    def phase(self):
        phase = self.controller.phase
        return f"{self.direction}_{phase.split('_')[-1]}" if "RED_TO" not in phase else "ALL_RED"

    def state(self, links):
        if self.phase == "ALL_RED":
            return "r" * len(links)
        char = "G" if self.phase.endswith("GREEN") else "y"
        result = []
        for group in links:
            origins = {incoming.rsplit("_", 1)[0] for incoming, _, _ in group}
            if not origins or any(not origin.startswith("in_") for origin in origins):
                raise ValueError("Ismeretlen szabályozott sávkapcsolat.")
            if len(origins) != 1:
                raise ValueError("Egy jelzés több különböző bevezető ághoz tartozik.")
            result.append(char if origins == {f"in_{self.direction}"} else "r")
        return "".join(result)

    def step_queues(self, queues):
        active = queues[self.direction]
        other = sum(queues.values()) - active
        before = self.controller.phase
        ns, ew = (active, other) if before.startswith("NS") else (other, active)
        after = self.controller.step(ns, ew)
        if after != before and after.endswith("GREEN"):
            self.index = (self.index + 1) % len(self.approaches)
            self._configure_green()
