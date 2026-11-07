from __future__ import annotations

import hashlib
import json
import random
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from smarttraffic_ai.controllers import ApproachController
from smarttraffic_ai.detection import MOTOR_VEHICLES
from smarttraffic_ai.flow import select_arrivals
from smarttraffic_ai.scene import TURN_DESTINATIONS, TrafficScene
from smarttraffic_ai.simulation import binary, output_directory, run_simulation, save_csv, save_json
from smarttraffic_ai.traffic import Demand, write_xml

VEHICLE_TYPES = {
    "car": {"vClass": "passenger", "length": "5", "color": "0.2,0.5,1"},
    "bus": {"vClass": "bus", "length": "12", "color": "1,0.7,0"},
    "truck": {"vClass": "truck", "length": "10", "color": "0.7,0.3,0.8"},
    "motorcycle": {"vClass": "motorcycle", "length": "2.5", "color": "0.2,0.9,0.5"},
}


def _destination(rng, settings, origin):
    choices = [
        (TURN_DESTINATIONS[origin][turn], weight)
        for turn, weight in settings.turns.items()
        if weight > 0 and TURN_DESTINATIONS[origin][turn] in settings.approaches
    ]
    return rng.choices([d for d, _ in choices], weights=[w for _, w in choices])[0]


def _build_scene_network(directory, scene):
    cfg = scene.settings
    nodes, edges, connections = ET.Element("nodes"), ET.Element("edges"), ET.Element("connections")
    ET.SubElement(
        nodes, "node", id="J", x="0", y="0", type="traffic_light" if cfg.signalized else "priority"
    )
    coordinates = {"N": (0, 1), "E": (1, 0), "S": (0, -1), "W": (-1, 0)}
    for side in cfg.approaches:
        x, y = coordinates[side]
        ET.SubElement(
            nodes,
            "node",
            id=side,
            x=str(x * cfg.arm_length),
            y=str(y * cfg.arm_length),
            type="dead_end",
        )
        for prefix, source, target in [("in", side, "J"), ("out", "J", side)]:
            ET.SubElement(
                edges,
                "edge",
                {
                    "id": f"{prefix}_{side}",
                    "from": source,
                    "to": target,
                    "numLanes": str(cfg.lanes),
                    "speed": str(cfg.speed_kmh / 3.6),
                },
            )
        for target in cfg.approaches:
            if target != side:
                # netconvert assigns turning lanes; no hand-edited network internals.
                ET.SubElement(
                    connections, "connection", {"from": f"in_{side}", "to": f"out_{target}"}
                )
    for kind, element in [("nod", nodes), ("edg", edges), ("con", connections)]:
        write_xml(element, directory / f"intersection.{kind}.xml")
    command = [
        binary("netconvert"),
        "--node-files",
        str(directory / "intersection.nod.xml"),
        "--edge-files",
        str(directory / "intersection.edg.xml"),
        "--connection-files",
        str(directory / "intersection.con.xml"),
        "--output-file",
        str(directory / "network.net.xml"),
        "--no-turnarounds",
        "true",
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    (directory / "netconvert.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise ValueError(f"A hálózat nem generálható; részletek: {directory / 'netconvert.log'}")
    return command


def _fixed_program(directory, scene):
    root = ET.parse(directory / "network.net.xml").getroot()
    controlled = [c for c in root.findall("connection") if c.get("tl") == "J"]
    if not controlled:
        raise ValueError("A generált hálózatban nincs jelzőlámpával vezérelt kapcsolat.")
    groups = [[] for _ in range(1 + max(int(c.get("linkIndex")) for c in controlled))]
    for c in controlled:
        groups[int(c.get("linkIndex"))].append(
            (f"{c.get('from')}_{c.get('fromLane')}", f"{c.get('to')}_{c.get('toLane')}", "")
        )
    controller = ApproachController(scene.settings.signals, scene.settings.approaches)
    additional = ET.Element("additional")
    tls = ET.SubElement(additional, "tlLogic", id="J", type="static", programID="scene", offset="0")
    if scene.settings.warmup_seconds:
        ET.SubElement(
            tls,
            "phase",
            name="WARMUP",
            duration=str(scene.settings.warmup_seconds),
            state="r" * len(groups),
        )
    # Two legacy controller cycles cover four arms; T-junctions stop after three services.
    for _ in range(len(scene.settings.approaches)):
        for suffix, seconds in [
            (
                "GREEN",
                scene.settings.signals.ns_green
                if controller.controller.phase.startswith("NS")
                else scene.settings.signals.ew_green,
            ),
            ("YELLOW", scene.settings.signals.yellow),
            ("RED", scene.settings.signals.all_red),
        ]:
            state = controller.state(groups) if suffix != "RED" else "r" * len(groups)
            ET.SubElement(tls, "phase", name=controller.phase, duration=str(seconds), state=state)
            for _ in range(seconds):
                controller.step_queues(dict.fromkeys(scene.settings.approaches, 0))
    tls[-1].set("next", "1" if scene.settings.warmup_seconds else "0")
    write_xml(additional, directory / "signals.add.xml")


def _write_scene_demand(directory, scene):
    cfg = scene.settings
    rng = random.Random(cfg.seed)
    routes = ET.Element("routes")
    for name, attributes in VEHICLE_TYPES.items():
        ET.SubElement(routes, "vType", id=name, sigma="0.5", minGap="2.5", **attributes)
    for side in cfg.approaches:
        for target in cfg.approaches:
            if target != side:
                ET.SubElement(
                    routes, "route", id=f"{side}-{target}", edges=f"in_{side} out_{target}"
                )
    import sumolib

    network = sumolib.net.readNet(str(directory / "network.net.xml"))
    events = []
    for approach in scene.approaches:
        origin = approach.id
        lane_used = [5.0] * cfg.lanes
        lane_lengths = [lane.getLength() for lane in network.getEdge(f"in_{origin}").getLanes()]
        for category, number in approach.initial_vehicles.items():
            for initial_index in range(number):
                destination = _destination(rng, cfg, origin)
                allowed = {
                    connection.getFromLane().getIndex()
                    for connection in network.getEdge(f"in_{origin}").getConnections(
                        network.getEdge(f"out_{destination}")
                    )
                }
                if not allowed:
                    raise ValueError(f"Nincs sávkapcsolat: {origin} → {destination}.")
                lane = min(allowed, key=lambda i: lane_used[i])
                length = float(VEHICLE_TYPES[category]["length"])
                position = lane_lengths[lane] - lane_used[lane]
                if position - length < 0:
                    raise ValueError(
                        f"A(z) {origin} ág kezdeti járművei nem férnek el; "
                        "növeld az ághosszt vagy a sávszámot."
                    )
                events.append(
                    {
                        "depart": 0.0,
                        "origin": origin,
                        "category": category,
                        "destination": destination,
                        "initial": True,
                        "lane": lane,
                        "position": position,
                        "source_track_id": sorted(
                            t.track_id
                            for t in scene.measured_flow.initial_tracks
                            if t.approach == origin and t.vehicle_type == category
                        )[initial_index]
                        if scene.measured_flow
                        else None,
                    }
                )
                lane_used[lane] += length + 2.5
        weights = [approach.vehicle_weights[c] for c in MOTOR_VEHICLES]
        if sum(weights) == 0:
            weights = [1, 0, 0, 0]
        for window in scene.estimated_arrivals:
            if cfg.arrival_mode == "measured":
                break
            rate = window.rates[origin]
            if rate == 0:
                continue
            depart = window.begin + rng.expovariate(rate / 3600)
            while depart < window.end:
                category = rng.choices(MOTOR_VEHICLES, weights=weights)[0]
                events.append(
                    {
                        "depart": depart,
                        "origin": origin,
                        "category": category,
                        "destination": _destination(rng, cfg, origin),
                        "initial": False,
                    }
                )
                depart += rng.expovariate(rate / 3600)
    if scene.measured_flow:
        arrivals, excluded = select_arrivals(scene.measured_flow)
        for event in arrivals:
            if event.approach not in cfg.approaches:
                raise ValueError("A mért belépés hiányzó SUMO-ágra hivatkozik.")
            events.append(
                {
                    "depart": cfg.warmup_seconds + event.timestamp_seconds,
                    "origin": event.approach,
                    "category": event.vehicle_type,
                    "destination": _destination(rng, cfg, event.approach),
                    "initial": False,
                    "source_track_id": event.track_id,
                    "source_line_id": event.line_id,
                    "source_event_seconds": event.timestamp_seconds,
                    "arrival_basis": "measured",
                }
            )
        save_json(directory / "flow-exclusions.json", excluded)
    events.sort(key=lambda e: (e["depart"], e["origin"]))
    for index, event in enumerate(events):
        event["id"] = f"v{index}"
        attributes = {
            "id": event["id"],
            "type": event["category"],
            "route": f"{event['origin']}-{event['destination']}",
            "depart": f"{event['depart']:.6f}",
            "departSpeed": "0",
            "departLane": "best",
        }
        if event["initial"]:
            # Explicit template placement; actual insertion is checked by the runner metrics.
            attributes.update(departLane=str(event["lane"]), departPos=f"{event['position']:.6f}")
        ET.SubElement(routes, "vehicle", attributes)
    write_xml(routes, directory / "demand.rou.xml")
    save_json(directory / "demand.json", events)
    return events


def generate_scene(root: Path, scene: TrafficScene) -> Path:
    scene = TrafficScene.model_validate(scene.model_dump())
    started = time.perf_counter()
    directory = output_directory(root, "scene")
    save_json(directory / "scene.json", scene.model_dump(mode="json"))
    if scene.measured_flow:
        save_json(directory / "flow-measurement.json", scene.measured_flow.model_dump(mode="json"))
        if scene.flow_validation:
            save_json(
                directory / "flow-validation.json", scene.flow_validation.model_dump(mode="json")
            )
    command = _build_scene_network(directory, scene)
    if scene.settings.signalized:
        _fixed_program(directory, scene)
    events = _write_scene_demand(directory, scene)
    config = ET.Element("configuration")
    inputs = ET.SubElement(config, "input")
    ET.SubElement(inputs, "net-file", value="network.net.xml")
    ET.SubElement(inputs, "route-files", value="demand.rou.xml")
    if scene.settings.signalized:
        ET.SubElement(inputs, "additional-files", value="signals.add.xml")
    times = ET.SubElement(config, "time")
    ET.SubElement(times, "end", value=str(scene.scenario().duration))
    randomness = ET.SubElement(config, "random_number")
    ET.SubElement(randomness, "seed", value=str(scene.settings.seed))
    write_xml(config, directory / "simulation.sumocfg")
    save_json(directory / "scenario.json", scene.scenario().model_dump())
    save_json(
        directory / "manifest.json",
        {
            "files": {
                name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
                for name in ("network.net.xml", "demand.rou.xml", "scene.json", "scenario.json")
            },
            "demand": len(events),
            "initial": sum(e["initial"] for e in events),
            "generation_seconds": time.perf_counter() - started,
            "netconvert_command": command,
        },
    )
    return directory


def load_generated(directory):
    directory = Path(directory).resolve()
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    for name in ("network.net.xml", "demand.rou.xml", "scene.json", "scenario.json"):
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != manifest["files"][name]:
            raise ValueError("A generált forgatókönyv megváltozott; generáld újra.")
    scene = TrafficScene.model_validate_json((directory / "scene.json").read_text(encoding="utf-8"))
    vehicles = ET.parse(directory / "demand.rou.xml").getroot().findall("vehicle")
    demand = [
        Demand(v.get("id"), float(v.get("depart")), v.get("route").split("-")[0]) for v in vehicles
    ]
    return scene, demand


def run_scene(root: Path, directory: Path, mode="fixed", gui=False):
    scene, _ = load_generated(directory)
    return run_simulation(
        root,
        scene.scenario(),
        mode,
        config=scene.settings.signals,
        seed=scene.settings.seed,
        gui=gui,
        prepared=directory,
    )


def compare_scene(root: Path, directory: Path):
    scene, _ = load_generated(directory)
    if not scene.settings.signalized:
        raise ValueError(
            "Jelzőlámpa nélküli helyzetben nincs fix/adaptív lámpaprogram-összehasonlítás."
        )
    results = [run_scene(root, directory, mode) for mode in ("fixed", "adaptive")]
    if (
        len({r["demand_sha256"] for r in results}) != 1
        or len({r["network_sha256"] for r in results}) != 1
    ):
        raise ValueError("Az összehasonlított forgalmi igény vagy hálózat eltér.")
    report = {
        "source_directory": str(directory),
        "runs": results,
        "note": "Azonos igény, seed és időhorizont. A várakozás az áthaladással "
        "és a maradó igénnyel együtt értékelendő.",
    }
    output = output_directory(root, "scene-comparison")
    report["directory"] = str(output)
    save_json(output / "comparison.json", report)
    save_csv(
        output / "comparison.csv",
        [{"controller": r["controller"], **r["metrics"]} for r in results],
    )
    return report
