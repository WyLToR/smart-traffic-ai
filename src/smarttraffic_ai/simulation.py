from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from smarttraffic_ai.config import AppConfig, Scenario, SignalConfig, load_scenario, load_yaml
from smarttraffic_ai.controllers import Controller, TrafficController, signal_states
from smarttraffic_ai.traffic import generate_demand, write_routes, write_xml


def binary(name: str) -> str:
    """Support system SUMO and the optional eclipse-sumo wheel."""
    executable = name + (".exe" if sys.platform == "win32" else "")
    found = shutil.which(name)
    if found:
        return found
    home = os.environ.get("SUMO_HOME")
    if home and (Path(home) / "bin" / executable).is_file():
        return str(Path(home) / "bin" / executable)
    try:
        import sumo

        candidate = Path(sumo.__file__).parent / "bin" / executable
        if candidate.is_file():
            return str(candidate)
    except ImportError:
        pass
    raise FileNotFoundError(
        f"Nem található: {name}. Telepítsd a SUMO-t, vagy: pip install -e '.[sumo]'. "
        "Ellenőrizd a SUMO_HOME és PATH beállítását."
    )


def build_network(root: Path) -> Path:
    directory = root / "sumo/networks"
    directory.mkdir(parents=True, exist_ok=True)
    nodes = ET.Element("nodes")
    ET.SubElement(nodes, "node", id="J", x="0", y="0", type="traffic_light")
    for side, (x, y) in {"N": (0, 250), "S": (0, -250), "E": (250, 0), "W": (-250, 0)}.items():
        ET.SubElement(nodes, "node", id=side, x=str(x), y=str(y), type="dead_end")
    edges = ET.Element("edges")
    connections = ET.Element("connections")
    for side, opposite in {"N": "S", "S": "N", "E": "W", "W": "E"}.items():
        ET.SubElement(
            edges,
            "edge",
            {"id": f"in_{side}", "from": side, "to": "J", "numLanes": "1", "speed": "13.89"},
        )
        ET.SubElement(
            edges,
            "edge",
            {"id": f"out_{side}", "from": "J", "to": side, "numLanes": "1", "speed": "13.89"},
        )
        ET.SubElement(
            connections,
            "connection",
            {"from": f"in_{side}", "to": f"out_{opposite}", "fromLane": "0", "toLane": "0"},
        )
    for kind, element in [("nod", nodes), ("edg", edges), ("con", connections)]:
        write_xml(element, directory / f"intersection.{kind}.xml")
    network = directory / "intersection.net.xml"
    subprocess.run(
        [
            binary("netconvert"),
            "--node-files",
            str(directory / "intersection.nod.xml"),
            "--edge-files",
            str(directory / "intersection.edg.xml"),
            "--connection-files",
            str(directory / "intersection.con.xml"),
            "--output-file",
            str(network),
            "--no-turnarounds",
            "true",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    # Install the same safe six-phase baseline for direct SUMO-GUI use.
    tree = ET.parse(network)
    tls = tree.getroot().find("tlLogic")
    if tls is None:
        raise ValueError("A generált hálózatban nincs jelzőlámpa.")
    links = sorted(
        (c for c in tree.getroot().findall("connection") if c.get("tl") == "J"),
        key=lambda c: int(c.get("linkIndex")),
    )
    states = signal_states([[(f"{c.get('from')}_0", f"{c.get('to')}_0", "")] for c in links])
    for child in list(tls):
        tls.remove(child)
    cfg = load_yaml(root / "config/simulation.yaml", SignalConfig)
    durations = [cfg.ns_green, cfg.yellow, cfg.all_red, cfg.ew_green, cfg.yellow, cfg.all_red]
    for (phase, state), duration in zip(states.items(), durations, strict=True):
        ET.SubElement(tls, "phase", duration=str(duration), state=state, name=phase)
    write_xml(tree.getroot(), network)
    for name in ("balanced", "rush-hour", "variable"):
        scenario = load_scenario(root, name)
        write_routes(generate_demand(scenario, scenario.seed), root / f"sumo/routes/{name}.rou.xml")
        demo = ET.Element("configuration")
        inputs = ET.SubElement(demo, "input")
        ET.SubElement(inputs, "net-file", value="../networks/intersection.net.xml")
        ET.SubElement(inputs, "route-files", value=f"../routes/{name}.rou.xml")
        times = ET.SubElement(demo, "time")
        ET.SubElement(times, "end", value=str(scenario.duration))
        random = ET.SubElement(demo, "random_number")
        ET.SubElement(random, "seed", value=str(scenario.seed))
        write_xml(demo, root / f"sumo/configs/{name}.sumocfg")
    return network


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )


def save_csv(path: Path, rows: list[dict]):
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def output_directory(root: Path, kind: str) -> Path:
    cfg = load_yaml(root / "config/app.yaml", AppConfig)
    path = root / cfg.output_dir / f"{kind}-{uuid.uuid4().hex[:12]}"
    path.mkdir(parents=True)
    return path


def run_simulation(
    root: Path,
    scenario: Scenario,
    mode: str = "fixed",
    config: SignalConfig | None = None,
    seed: int | None = None,
    gui: bool = False,
) -> dict:
    import traci

    cfg = config or load_yaml(root / "config/simulation.yaml", SignalConfig)
    controller: TrafficController = Controller(cfg, mode)
    seed = scenario.seed if seed is None else seed
    executable = binary("sumo-gui" if gui else "sumo")
    network = root / "sumo/networks/intersection.net.xml"
    if not network.is_file():
        network = build_network(root)
    directory = output_directory(root, "run")
    # Snapshot the network: subsequent builds cannot change an archived experiment.
    shutil.copy2(network, directory / "network.net.xml")
    demand = generate_demand(scenario, seed)
    write_routes(demand, directory / "demand.rou.xml")
    sumocfg = ET.Element("configuration")
    inputs = ET.SubElement(sumocfg, "input")
    ET.SubElement(inputs, "net-file", value="network.net.xml")
    ET.SubElement(inputs, "route-files", value="demand.rou.xml")
    times = ET.SubElement(sumocfg, "time")
    ET.SubElement(times, "begin", value="0")
    ET.SubElement(times, "end", value=str(scenario.duration))
    write_xml(sumocfg, directory / "simulation.sumocfg")
    command = [
        executable,
        "-c",
        str(directory / "simulation.sumocfg"),
        "--seed",
        str(seed),
        "--step-length",
        "1",
        "--time-to-teleport",
        "-1",
        "--no-step-log",
        "true",
        "--duration-log.disable",
        "true",
        "--tripinfo-output",
        str(directory / "tripinfo.xml"),
        "--tripinfo-output.write-unfinished",
        "true",
        "--error-log",
        str(directory / "sumo-errors.log"),
    ]
    if gui:
        command += ["--start", "--quit-on-end"]
    label = uuid.uuid4().hex
    connection = None
    rows = []
    stopped = defaultdict(int)
    departure = {}
    arrived = set()
    travel = []
    collisions = 0
    try:
        traci.start(command, label=label, doSwitch=False, stdout=subprocess.DEVNULL)
        connection = traci.getConnection(label)
        version = connection.getVersion()
        states = signal_states(connection.trafficlight.getControlledLinks("J"))
        connection.trafficlight.setRedYellowGreenState("J", states[controller.phase])
        for _ in range(scenario.duration):
            phase = controller.phase
            connection.simulationStep()
            collisions += connection.simulation.getCollidingVehiclesNumber()
            time = int(connection.simulation.getTime())
            for vehicle in connection.simulation.getDepartedIDList():
                departure[vehicle] = time - 1
            for vehicle in connection.simulation.getArrivedIDList():
                arrived.add(vehicle)
                travel.append(time - 1 - departure[vehicle])
            active = connection.vehicle.getIDList()
            for vehicle in active:
                if connection.vehicle.getSpeed(vehicle) < 0.1:
                    stopped[vehicle] += 1
            queues = {
                side: connection.lane.getLastStepHaltingNumber(f"in_{side}_0")
                for side in ("N", "S", "E", "W")
            }
            ns, ew = queues["N"] + queues["S"], queues["E"] + queues["W"]
            rows.append(
                {
                    "time": time,
                    "phase": phase,
                    "signal": states[phase],
                    "ns_queue": ns,
                    "ew_queue": ew,
                    "queue": ns + ew,
                    "active": len(active),
                    "arrived": len(arrived),
                    "pending": sum(1 for v in demand if v.depart < time and v.id not in departure),
                }
            )
            next_phase = controller.step(ns, ew)
            if next_phase != phase:
                connection.trafficlight.setRedYellowGreenState("J", states[next_phase])
    finally:
        if connection is not None:
            connection.close()
    waits = {
        v.id: stopped[v.id] + max(0, departure.get(v.id, scenario.duration) - v.depart)
        for v in demand
    }
    pending = len(demand) - len(departure)
    remaining = len(demand) - len(arrived)
    metrics = {
        "demand": len(demand),
        "departed": len(departure),
        "arrived": len(arrived),
        "remaining": remaining,
        "pending": pending,
        "active_at_end": len(departure) - len(arrived),
        "waiting_at_end": rows[-1]["queue"] + pending,
        "mean_wait": sum(waits.values()) / max(1, len(demand)),
        "max_wait": max(waits.values(), default=0),
        "mean_travel_completed": sum(travel) / len(travel) if travel else None,
        "mean_queue": sum(row["queue"] for row in rows) / scenario.duration,
        "max_queue": max(row["queue"] for row in rows),
        "total_stopped_seconds": sum(stopped.values()),
        "total_insertion_delay": sum(waits.values()) - sum(stopped.values()),
        "collision_vehicle_events": collisions,
    }
    result = {
        "scenario": scenario.model_dump(),
        "controller": mode,
        "seed": seed,
        "signals": cfg.model_dump(),
        "metrics": metrics,
        "directory": str(directory),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sumo_version": list(version),
        "python_version": sys.version,
        "package_version": importlib.metadata.version("smarttraffic-ai"),
        "demand_sha256": hashlib.sha256((directory / "demand.rou.xml").read_bytes()).hexdigest(),
        "network_sha256": hashlib.sha256((directory / "network.net.xml").read_bytes()).hexdigest(),
        "command": command,
    }
    save_json(directory / "scenario.json", scenario.model_dump())
    save_json(directory / "result.json", result)
    save_csv(directory / "metrics.csv", [metrics])
    save_csv(directory / "timeline.csv", rows)
    return result
