import csv
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import pytest

from smarttraffic_ai.config import SignalConfig, project_root
from smarttraffic_ai.detection import Detection, DetectionResult
from smarttraffic_ai.scene import SceneSettings, analyze_image
from smarttraffic_ai.scene_sumo import compare_scene, generate_scene, load_generated, run_scene
from smarttraffic_ai.simulation import binary

try:
    binary("sumo")
    binary("netconvert")
    HAS_SUMO = True
except FileNotFoundError:
    HAS_SUMO = False

pytestmark = [pytest.mark.sumo, pytest.mark.skipif(not HAS_SUMO, reason="SUMO nem érhető el")]


def scene_for_test(**overrides):
    categories = ["car"] * 16 + ["bus"] * 2 + ["truck"] * 2 + ["motorcycle"] * 4
    detection = DetectionResult(
        source_id="integration",
        timestamp=datetime.now(timezone.utc),
        timestamp_source="user",
        source="mock",
        width=64,
        height=64,
        processing_seconds=0,
        model_path=None,
        objects=[Detection(category=c, confidence=0.9, bbox=(1, 1, 20, 20)) for c in categories],
    )
    settings = SceneSettings(
        object_directions={i: "N" if i < 16 else "E" for i in range(24)},
        signals=SignalConfig(min_green=8, max_green=20, ns_green=15, ew_green=15),
        **overrides,
    )
    return analyze_image(detection, settings), detection


@pytest.mark.parametrize(
    "intersection,lanes,signalized",
    [
        ("four_way", 1, True),
        ("t_junction", 2, True),
        ("four_way", 1, False),
    ],
)
def test_generated_scene_moves_typed_vehicles_and_records_real_results(
    intersection, lanes, signalized
):
    scene, _ = scene_for_test(intersection_type=intersection, lanes=lanes, signalized=signalized)
    root = project_root()
    directory = generate_scene(root, scene)
    result = run_scene(root, directory)
    metrics = result["metrics"]
    assert metrics["demand"] == 24
    assert metrics["demand_N"] == 16 and metrics["demand_E"] == 8
    assert metrics["demand_bus"] == 2 and metrics["demand_motorcycle"] == 4
    assert metrics["departed"] > 0 and metrics["arrived"] > 0
    assert metrics["moving_vehicle_steps"] > 0
    assert metrics["collision_vehicle_events"] == 0
    assert metrics["demand"] == metrics["arrived"] + metrics["remaining"]
    assert metrics["remaining"] == metrics["pending"] + metrics["active_at_end"]
    if signalized:
        assert metrics["red_stopped_vehicle_steps"] > 0
        assert metrics["warmup_departed"] == 24
    assert (directory / "intersection.nod.xml").is_file()
    assert (directory / "simulation.sumocfg").is_file()
    run_path = __import__("pathlib").Path(result["directory"])
    assert ET.parse(run_path / "tripinfo.xml").getroot().findall("tripinfo")
    assert (run_path / "result.json").is_file()
    if signalized:
        with (run_path / "timeline.csv").open(encoding="utf-8-sig") as stream:
            rows = list(csv.DictReader(stream))
        network = ET.parse(directory / "network.net.xml").getroot()
        by_index = {
            int(c.get("linkIndex")): c.get("from")
            for c in network.findall("connection")
            if c.get("tl") == "J"
        }
        for row in rows:
            origins = {by_index[i] for i, state in enumerate(row["signal"]) if state in "Gy"}
            assert len(origins) <= 1


def test_comparison_reuses_demand_network_seed_and_time_horizon():
    scene, _ = scene_for_test(arrival_rates={"N": 300, "E": 100, "S": 0, "W": 0})
    directory = generate_scene(project_root(), scene)
    second = generate_scene(project_root(), scene)
    assert (directory / "demand.rou.xml").read_bytes() == (second / "demand.rou.xml").read_bytes()
    results = compare_scene(project_root(), directory)["runs"]
    assert results[0]["demand_sha256"] == results[1]["demand_sha256"]
    assert results[0]["network_sha256"] == results[1]["network_sha256"]
    assert results[0]["seed"] == results[1]["seed"]
    assert results[0]["scenario"] == results[1]["scenario"]
    assert results[0]["metrics"]["demand"] > 24
    (directory / "demand.rou.xml").write_text("<routes/>", encoding="utf-8")
    with pytest.raises(ValueError, match="megváltozott"):
        load_generated(directory)


def test_zero_demand_and_initial_capacity_error():
    scene, _ = scene_for_test()
    for approach in scene.approaches:
        approach.initial_vehicles = dict.fromkeys(approach.initial_vehicles, 0)
    directory = generate_scene(project_root(), scene)
    assert run_scene(project_root(), directory)["metrics"]["demand"] == 0
    scene.approaches[0].initial_vehicles["bus"] = 100
    with pytest.raises(ValueError, match="nem férnek"):
        generate_scene(project_root(), scene)


def test_dashboard_generates_and_runs_the_selected_observation(monkeypatch):
    from streamlit.testing.v1 import AppTest

    from smarttraffic_ai import dashboard_scene

    scene, detection = scene_for_test()
    path = project_root() / "observation.json"
    path.write_text(detection.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(
        dashboard_scene, "_mapping_editor", lambda *args: scene.settings.object_directions
    )
    app = AppTest.from_string(
        "import streamlit as st\n"
        "from smarttraffic_ai.config import project_root\n"
        "from smarttraffic_ai.dashboard_scene import render_scene_tab\n"
        "st.session_state['detection'] = str(project_root() / 'observation.json')\n"
        "render_scene_tab(project_root(), True)"
    ).run()
    assert not app.exception
    next(c for c in app.checkbox if c.label.startswith("Ellenőriztem")).check().run()
    next(b for b in app.button if b.label == "SUMO-forgatókönyv létrehozása").click().run(
        timeout=20
    )
    assert not app.exception
    assert "scene_bundle" in app.session_state
    next(b for b in app.button if b.label == "Generált forgalom indítása").click().run(timeout=30)
    assert not app.exception
    assert app.session_state["scene_run"]["metrics"]["demand"] == 24
    next(n for n in app.number_input if n.label.startswith("Ághossz")).set_value(300.0).run()
    assert not any(b.label == "Generált forgalom indítása" for b in app.button)
