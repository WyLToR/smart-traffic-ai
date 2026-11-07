import json
from pathlib import Path

import pytest

from smarttraffic_ai.config import project_root
from smarttraffic_ai.detection import Region
from smarttraffic_ai.flow import (
    CameraProfile,
    CountingLine,
    FlowMeasurement,
    measure_flow,
    select_arrivals,
)
from smarttraffic_ai.flow_validation import ManualReference, evaluate_flow
from smarttraffic_ai.scene import SceneSettings, analyze_video
from smarttraffic_ai.scene_sumo import generate_scene, run_scene
from smarttraffic_ai.simulation import binary


@pytest.fixture
def measurement_fixture():
    root = project_root()
    folder = root / "synthetic-tracks"
    folder.mkdir()
    camera = CameraProfile(
        camera_id="synthetic-known-arrivals",
        fixed_view_confirmed=True,
        reference_size=(100, 100),
        zones=[
            Region(id="north", direction="N", bounds=(0, 0, 0.5, 0.45)),
            Region(id="east", direction="E", bounds=(0.5, 0.55, 1, 1)),
        ],
        lines=[
            CountingLine(
                id="n-entry",
                zone_id="north",
                approach="N",
                start=(0.25, 0.1),
                end=(0.25, 0.4),
                inbound="positive_to_negative",
            ),
            CountingLine(
                id="e-entry",
                zone_id="east",
                approach="E",
                start=(0.75, 0.6),
                end=(0.75, 0.9),
                inbound="negative_to_positive",
            ),
        ],
        window_seconds=10,
    )
    starts = [(1, 0, "N"), (2, 0, "E")] + [
        (i + 3, 10 + 6 * i, "N" if i % 2 == 0 else "E") for i in range(20)
    ]
    rows = []
    for index in range(140):
        objects = []
        for track_id, start, side in starts:
            step = index - start
            if 0 <= step < 6:
                x = [0.1, 0.15, 0.35, 0.4, 0.42, 0.44][step]
                x, y = (x, 0.25) if side == "N" else (1 - x, 0.8)
                objects.append(
                    {
                        "track_id": track_id,
                        "category": "car",
                        "bbox": [x - 0.01, y - 0.02, x + 0.01, y],
                    }
                )
        rows.append({"seconds": index / 10, "duration": 0.1, "objects": objects})
    analysis = folder / "analysis.json"
    analysis.write_text(
        json.dumps(
            {
                "input_sha256": "synthetic-source",
                "duration_seconds": 14,
                "width": 100,
                "height": 100,
                "frames": 140,
                "processing_seconds": 0,
                "tracks": [{"track_id": t, "category": "car"} for t, _, _ in starts],
            }
        ),
        encoding="utf-8",
    )
    (folder / "observations.jsonl").write_text(
        "\n".join(map(json.dumps, rows)) + "\n", encoding="utf-8"
    )
    path = measure_flow(root, analysis, camera)
    measurement = FlowMeasurement.model_validate_json(path.read_text(encoding="utf-8"))
    reference = ManualReference.model_validate(
        {
            "camera_id": camera.camera_id,
            "source_sha256": "synthetic-source",
            "profile_sha256": measurement.profile_sha256,
            "annotator": "synthetic known trajectory fixture, not real-camera accuracy",
            "human_reviewed": True,
            "segments": [
                {
                    "begin": begin,
                    "end": end,
                    "events": [
                        {
                            "timestamp_seconds": start / 10 + 0.15,
                            "line_id": "n-entry" if side == "N" else "e-entry",
                            "vehicle_type": "car",
                        }
                        for _, start, side in starts
                        if begin <= start / 10 + 0.15 < end
                    ],
                }
                for begin, end in [(0, 7), (7, 14)]
            ],
        }
    )
    return analysis, path, measurement, reference


def test_known_events_aggregate_exactly_and_initial_vehicles_are_not_new_arrivals(
    measurement_fixture,
):
    _, _, measurement, reference = measurement_fixture
    assert len(measurement.events) == 22
    arrivals, excluded = select_arrivals(measurement)
    assert len(arrivals) == 20
    assert excluded["already_initial"] == 2
    assert sum(sum(w.inbound_counts.values()) for w in measurement.windows) == 22
    assert measurement.windows[0].inbound_counts["N"] == 9
    assert measurement.windows[0].inbound_counts["E"] == 8
    assert measurement.windows[1].inbound_counts["N"] == 2
    assert measurement.windows[1].inbound_counts["E"] == 3
    report = evaluate_flow(measurement, reference, 0.05)
    assert report.f1 == 1 and report.approved_for_arrivals
    assert report.true_positives == 22 and report.false_positives == report.false_negatives == 0


def test_unreviewed_reference_and_duplicate_predictions_do_not_create_a_false_pass(
    measurement_fixture,
):
    _, _, measurement, reference = measurement_fixture
    reference.human_reviewed = False
    assert not evaluate_flow(measurement, reference).approved_for_arrivals
    measurement.events.append(measurement.events[-1].model_copy(update={"track_id": 999}))
    report = evaluate_flow(measurement, reference)
    assert report.false_positives == 1
    assert report.precision < 1
    reference.source_sha256 = "different-video"
    with pytest.raises(ValueError, match="másik kamerához"):
        evaluate_flow(measurement, reference)


def test_measured_times_feed_sumo_once_without_poisson_or_time_stretching(measurement_fixture):
    analysis, path, measurement, reference = measurement_fixture
    report = evaluate_flow(measurement, reference)
    validation = path.parent / "validation.json"
    validation.write_text(report.model_dump_json(), encoding="utf-8")
    settings = SceneSettings(
        arrival_mode="measured",
        flow_measurement_path=str(path),
        flow_validation_path=str(validation),
        simulation_seconds=120,
        arm_length=50,
    )
    scene = analyze_video(analysis, settings)
    assert scene.settings.simulation_seconds == 14
    assert scene.scenario().duration == 19
    assert scene.measured_flow is not None
    try:
        binary("sumo")
        binary("netconvert")
    except FileNotFoundError:
        pytest.skip("SUMO szükséges a generátor ellenőrzéséhez.")
    directory = generate_scene(project_root(), scene)
    demand = json.loads((directory / "demand.json").read_text(encoding="utf-8"))
    assert len(demand) == 22
    assert sum(e["initial"] for e in demand) == 2
    measured = [e for e in demand if not e["initial"]]
    assert len({e["source_track_id"] for e in measured}) == 20
    assert all(e["depart"] == pytest.approx(e["source_event_seconds"] + 5) for e in measured)
    result = run_scene(project_root(), directory)
    assert result["metrics"]["demand"] == 22
    assert result["metrics"]["departed"] > 0
    assert result["metrics"]["arrived"] > 0
    assert result["metrics"]["demand_N"] == result["metrics"]["demand_E"] == 11
    assert result["metrics"]["measured_arrivals"] == 20
    assert result["metrics"]["measured_inserted"] + result["metrics"]["measured_pending"] == 20
    assert (Path(result["directory"]) / "vehicle-demand.csv").is_file()


def test_measured_mode_requires_matching_validation_or_explicit_experimental_mode(
    measurement_fixture,
):
    analysis, path, _, _ = measurement_fixture
    settings = SceneSettings(arrival_mode="measured", flow_measurement_path=str(path))
    with pytest.raises(ValueError, match="még nem igazolt"):
        analyze_video(analysis, settings)
    settings.allow_unvalidated_flow = True
    scene = analyze_video(analysis, settings)
    assert any("KÍSÉRLETI" in text for text in scene.assumptions)
    from smarttraffic_ai.simulation import run_simulation

    with pytest.raises(ValueError, match="scene-run"):
        run_simulation(project_root(), scene.scenario())


def test_empty_reference_does_not_manufacture_perfect_accuracy(measurement_fixture):
    _, _, measurement, reference = measurement_fixture
    measurement.events = []
    for segment in reference.segments:
        segment.events = []
    report = evaluate_flow(measurement, reference)
    assert report.f1 is report.recall is report.precision is None
    assert not report.sufficient_sample and not report.approved_for_arrivals


def test_reference_matching_is_one_to_one_even_with_nearby_events():
    from types import SimpleNamespace

    from smarttraffic_ai.flow_validation import _match

    expected = [SimpleNamespace(timestamp_seconds=t) for t in [0, 1]]
    predicted = [SimpleNamespace(timestamp_seconds=t) for t in [0.7, 1.8]]
    assert _match(expected, predicted, 0.8) == 2


def test_measurement_is_invalid_after_tracking_export_changes(measurement_fixture):
    analysis, path, _, _ = measurement_fixture
    observations = analysis.parent / "observations.jsonl"
    rows = [json.loads(line) for line in observations.read_text(encoding="utf-8").splitlines()]
    rows[-1]["objects"] = [{"track_id": 22, "category": "car", "bbox": [0.1, 0.1, 0.2, 0.2]}]
    observations.write_text("\n".join(map(json.dumps, rows)) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="megváltozott"):
        analyze_video(
            analysis,
            SceneSettings(
                arrival_mode="measured",
                flow_measurement_path=str(path),
                allow_unvalidated_flow=True,
            ),
        )


def test_flow_dashboard_can_measure_a_saved_camera_profile(measurement_fixture):
    import shutil

    from streamlit.testing.v1 import AppTest

    analysis, _, measurement, _ = measurement_fixture
    folder = project_root() / "outputs/video-known"
    folder.mkdir(parents=True)
    shutil.copy2(analysis, folder / "analysis.json")
    shutil.copy2(analysis.parent / "observations.jsonl", folder / "observations.jsonl")
    camera_path = project_root() / "config/cameras/known.json"
    camera_path.parent.mkdir(exist_ok=True)
    camera_path.write_text(measurement.camera.model_dump_json(), encoding="utf-8")
    app = AppTest.from_string(
        "from smarttraffic_ai.config import project_root\n"
        "from smarttraffic_ai.dashboard_flow import render_flow_tab\n"
        "render_flow_tab(project_root())"
    ).run()
    assert not app.exception
    app.selectbox(key="flow-preset").set_value(camera_path).run()
    next(c for c in app.checkbox if c.label.startswith("Ellenőriztem:")).check().run()
    next(c for c in app.checkbox if c.label == "Jelölt mérési videó mentése").uncheck().run()
    next(b for b in app.button if b.label == "Forgalommérés indítása").click().run()
    assert not app.exception
    assert "flow_measurement" in app.session_state
    saved = FlowMeasurement.model_validate_json(
        Path(app.session_state["flow_measurement"]).read_text(encoding="utf-8")
    )
    assert len(saved.events) == 22


def test_scene_dashboard_replays_the_selected_measurement(measurement_fixture, monkeypatch):
    from streamlit.testing.v1 import AppTest

    from smarttraffic_ai import dashboard_scene

    analysis, path, measurement, reference = measurement_fixture
    report = evaluate_flow(measurement, reference)
    (path.parent / "validation.json").write_text(report.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(dashboard_scene, "_mapping_editor", lambda *args: {})
    app = AppTest.from_string(
        "import streamlit as st\n"
        "from smarttraffic_ai.config import project_root\n"
        "from smarttraffic_ai.dashboard_scene import render_scene_tab\n"
        "st.session_state['video_result']={'directory':str(project_root()/'synthetic-tracks')}\n"
        "render_scene_tab(project_root(), True)"
    ).run()
    app.radio(key="scene-input").set_value("Legutóbbi videó").run()
    app.radio(key="scene-arrivals").set_value("measured").run()
    assert not app.exception
    assert not app.error
    next(c for c in app.checkbox if c.label.startswith("Ellenőriztem az ágak")).check().run()
    next(b for b in app.button if b.label == "SUMO-forgatókönyv létrehozása").click().run(
        timeout=20
    )
    assert not app.exception and "scene_bundle" in app.session_state
    demand = json.loads(
        (Path(app.session_state["scene_bundle"]) / "demand.json").read_text(encoding="utf-8")
    )
    assert len(demand) == 22
