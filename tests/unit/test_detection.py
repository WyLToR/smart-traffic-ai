import json
import shutil
from datetime import datetime, timezone

import pytest
from PIL import Image
from pydantic import ValidationError

from smarttraffic_ai.config import project_root
from smarttraffic_ai.detection import (
    Detection,
    DetectionConfig,
    DetectionResult,
    Region,
    assign_regions,
    detect_file,
)
from smarttraffic_ai.estimation import estimate_scenarios


def observation(objects=None):
    return DetectionResult(
        source_id="test",
        timestamp=datetime.now(timezone.utc),
        timestamp_source="user",
        source="mock",
        width=100,
        height=100,
        processing_seconds=0,
        model_path=None,
        objects=objects or [],
    )


def test_bottom_center_and_unassigned_objects():
    cfg = DetectionConfig(regions=[Region(id="n", direction="N", bounds=(0, 0, 0.5, 0.5))])
    objects = [
        Detection(category="car", bbox=(10, 10, 20, 30), confidence=0.9),
        Detection(category="bus", bbox=(60, 60, 80, 90), confidence=0.9),
    ]
    assigned = assign_regions(objects, cfg, 100, 100)
    result = observation(assigned)
    assert result.summary()["by_direction"] == {"N": 1, "S": 0, "E": 0, "W": 0}
    assert result.summary()["unassigned"] == 1
    assert objects[0].region is None  # preserve input records


def test_overlapping_regions_rejected():
    with pytest.raises(ValidationError):
        DetectionConfig(
            regions=[
                Region(id="n", direction="N", bounds=(0, 0, 0.5, 0.5)),
                Region(id="s", direction="S", bounds=(0.2, 0.2, 1, 1)),
            ]
        )


def test_pedestrians_do_not_become_motor_vehicle_counts():
    result = observation(
        [
            Detection(
                category="person", bbox=(1, 1, 10, 20), confidence=0.9, region="n", direction="N"
            ),
            Detection(
                category="car", bbox=(20, 20, 40, 40), confidence=0.9, region="n", direction="N"
            ),
        ]
    )
    assert result.summary()["by_category"]["person"] == 1
    assert result.summary()["by_direction"]["N"] == 1
    estimate, _ = estimate_scenarios(result)
    assert estimate["observed_counts"]["N"] == 1


@pytest.mark.parametrize("bbox", [(5, 5, 1, 1), (-1, 0, 1, 1), (0, 0, float("nan"), 1)])
def test_bad_bounding_boxes(bbox):
    with pytest.raises(ValidationError):
        Detection(category="car", bbox=bbox, confidence=0.9)


def test_counts_are_not_arrival_measurements():
    objects = [
        Detection(category="car", bbox=(1, 1, 2, 2), confidence=1, region="north", direction="N")
        for _ in range(15)
    ]
    estimate, scenarios = estimate_scenarios(observation(objects), prior_rate=400)
    assert estimate["observed_counts"]["N"] == 15
    assert [s.windows[0].rates["N"] for s in scenarios] == [200, 400, 600]
    assert all(s.source == "mock-estimate" for s in scenarios)
    assert all(s.windows[0].rates["W"] > 0 for s in scenarios)


def test_end_to_end_mock_and_missing_model(tmp_path):
    shutil.copytree(project_root() / "config", tmp_path / "config")
    path = tmp_path / "közlekedés.png"
    Image.new("RGB", (320, 240), "gray").save(path)
    result_path = detect_file(tmp_path, path, mock=True)
    result = DetectionResult.model_validate_json(result_path.read_text(encoding="utf-8"))
    assert result.source == "mock"
    assert len(result.objects) == 2
    assert result.timestamp_source == "file-mtime"
    assert (result_path.parent / "annotated.png").is_file()
    assert (
        json.loads((result_path.parent / "summary.json").read_text(encoding="utf-8"))["total"] == 2
    )
    with pytest.raises(FileNotFoundError, match="YOLO"):
        detect_file(tmp_path, path)


@pytest.mark.parametrize("rate", [-1, 5001, float("nan")])
def test_invalid_prior(rate):
    with pytest.raises(ValueError):
        estimate_scenarios(observation(), rate)


def test_timestamp_requires_timezone():
    data = observation().model_dump()
    data["timestamp"] = datetime(2026, 1, 1)
    with pytest.raises(ValidationError):
        DetectionResult.model_validate(data)
