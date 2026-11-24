import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from smarttraffic_ai.detection import Detection, DetectionResult, Region
from smarttraffic_ai.scene import SceneSettings, analyze_image, analyze_video


def observation(categories=("car", "bus", "person", "bicycle")):
    return DetectionResult(
        source_id="unit-image",
        timestamp=datetime.now(timezone.utc),
        timestamp_source="user",
        source="mock",
        width=100,
        height=100,
        processing_seconds=0,
        model_path=None,
        objects=[Detection(category=c, confidence=0.9, bbox=(10, 10, 30, 30)) for c in categories],
    )


def test_image_occupancy_is_initial_load_and_arrivals_remain_explicit():
    scene = analyze_image(
        observation(), SceneSettings(object_directions={0: "N", 1: "E", 2: "N", 3: "E"})
    )
    assert scene.approaches[0].initial_vehicles == {"car": 1, "bus": 0, "truck": 0, "motorcycle": 0}
    assert scene.approaches[1].initial_vehicles["bus"] == 1
    assert scene.approaches[0].observed_counts["person"] == 1
    assert all(a.estimated_queue_length is None for a in scene.approaches)
    assert all(sum(w.rates.values()) == 0 for w in scene.estimated_arrivals)


def test_unmapped_and_manually_excluded_objects_are_not_silently_simulated():
    zones = [Region(id="verified-view", direction="E", bounds=(0, 0, 1, 1))]
    scene = analyze_image(
        observation(), SceneSettings(regions=zones, object_directions={0: "N", 1: None})
    )
    assert scene.approaches[0].observed_counts["car"] == 1
    assert scene.unassigned_counts["bus"] == 1
    assert analyze_image(observation(), SceneSettings()).unassigned_counts["car"] == 1


@pytest.mark.parametrize(
    "settings",
    [
        {"arrival_rates": {"N": -1, "E": 0, "S": 0, "W": 0}},
        {"turns": {"straight": 0.9, "left": 0.5, "right": -0.4}},
        {"intersection_type": "t_junction", "missing_arm": "N", "object_directions": {0: "N"}},
    ],
)
def test_invalid_scene_parameters(settings):
    with pytest.raises(ValidationError):
        SceneSettings(**settings)


def test_video_uses_timestamped_occupancy_not_unique_ids_as_arrival_rate(tmp_path):
    data = {
        "tracks": [{"track_id": 1, "category": "car"}, {"track_id": 2, "category": "bus"}],
        "duration_seconds": 3,
        "input_sha256": "unit-video",
        "processing_seconds": 0,
    }
    path = tmp_path / "analysis.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    car = {"track_id": 1, "bbox": [0.1, 0.1, 0.3, 0.3]}
    bus = {"track_id": 2, "bbox": [0.6, 0.1, 0.9, 0.3]}
    rows = [
        {"seconds": 0, "duration": 0.25, "objects": [car]},
        {"seconds": 0.25, "duration": 0.75, "objects": [car, bus]},
        {"seconds": 1, "duration": 1, "objects": []},
        {"seconds": 2, "duration": 1, "objects": [car]},
    ]
    (tmp_path / "observations.jsonl").write_text("\n".join(map(json.dumps, rows)), encoding="utf-8")
    settings = SceneSettings(
        regions=[
            Region(id="a", direction="N", bounds=(0, 0, 0.5, 1)),
            Region(id="b", direction="E", bounds=(0.5, 0, 1, 1)),
        ],
        arrival_mode="occupancy-weighted",
        video_window_seconds=1,
    )
    scene = analyze_video(path, settings)
    assert scene.source_type == "video"
    assert scene.approaches[0].initial_vehicles["car"] == 1
    assert scene.approaches[1].initial_vehicles["bus"] == 0
    assert scene.approaches[0].observed_unique_tracks == 1
    assert scene.occupancy_windows[0].mean_counts["E"]["bus"] == pytest.approx(0.75)
    assert sum(scene.occupancy_windows[1].mean_counts["N"].values()) == 0
    assert scene.estimated_arrivals[1].rates["N"] > scene.estimated_arrivals[1].rates["E"]
    # Only the two zoned arms share the per-arm prior; S and W are not observed.
    assert sum(scene.estimated_arrivals[1].rates.values()) == pytest.approx(2 * settings.prior_rate)
    assert all(rate == 0 for rate in scene.estimated_arrivals[2].rates.values())
    assert "nem érkezésmérés" in scene.provenance["estimated_arrivals"]
    rows[-1]["seconds"] = -1
    (tmp_path / "observations.jsonl").write_text("\n".join(map(json.dumps, rows)), encoding="utf-8")
    with pytest.raises(ValueError, match="időbélyeg"):
        analyze_video(path, settings)
